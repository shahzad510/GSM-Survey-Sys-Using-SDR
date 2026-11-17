"""Android phone used as a measurement source over ADB.

The phone is not an SDR. Through ADB, without root, it yields only what
Android's own diagnostics print. This module keeps three classes of data apart
(see :class:`~cellsurvey.receivers.base.AccessMethod`):

* **Documented API** (``android.telephony``): reachable only from an app
  running on the phone. This receiver installs no app, so nothing is obtained
  this way.
* **Device diagnostics**: ``getprop`` and ``dumpsys`` run as the ``shell``
  user, which the owner authorizes by accepting USB debugging.
* **Unavailable**: raw modem diagnostics and RF samples.

The diagnostic formats handled here were observed on a Samsung SM-A600F
running Android 10. Other models and Android versions may print them
differently; anything not recognised is reported as unavailable.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from cellsurvey.receivers.adb import AdbClient, AdbDevice, AdbError
from cellsurvey.receivers.base import (
    AccessMethod,
    BaseReceiver,
    Capability,
    CapabilityReport,
    ConnectionState,
    ReceiverError,
    ReceiverInfo,
    ReceiverKind,
)

logger = logging.getLogger(__name__)

_STATES = {
    "device": ConnectionState.READY,
    "unauthorized": ConnectionState.UNAUTHORIZED,
    "offline": ConnectionState.OFFLINE,
    "no permissions": ConnectionState.NO_PERMISSIONS,
}

# Data name -> system property.
_TELEPHONY_PROPERTIES = (
    ("Network technology", "gsm.network.type"),
    ("Operator name", "gsm.operator.alpha"),
    ("Operator MCC and MNC", "gsm.operator.numeric"),
)

# (data name, field printed by `dumpsys telephony.registry`, pattern a value
# must contain to count as populated). The dump has one block per SIM slot.
_REGISTRY_COMMAND = "dumpsys telephony.registry"
_REGISTRY_FIELDS: tuple[tuple[str, str, re.Pattern[str] | None], ...] = (
    ("Service state", "mServiceState", None),
    # A slot without service prints "mWcdma=Invalid,mLte=Invalid,..." only.
    ("Signal strength", "mSignalStrength", re.compile(r"CellSignalStrength\w+: \w+=")),
    ("Cell information", "mCellInfo", None),
)
_EMPTY_VALUES = frozenset({"", "null", "[]"})

# Area code and cell identity inside CellIdentity records. Android 10 prints
# "<MASKED>" for these in diagnostic output.
_CELL_IDENTITY = re.compile(r"\bm(?:Lac|Tac|Cid|Ci)=(\S+)")
_MASKED = "<MASKED>"
_UNAVAILABLE_NUMBER = "2147483647"  # Integer.MAX_VALUE, Android's "not available"

_NOT_OBTAINABLE = (
    Capability(
        name="Android telephony API",
        access=AccessMethod.UNAVAILABLE,
        source="android.telephony (on-device app)",
        detail="Documented, but reachable only from an app installed on the phone. "
        "This receiver uses ADB only and installs nothing.",
    ),
    Capability(
        name="Raw modem diagnostics",
        access=AccessMethod.UNAVAILABLE,
        source="Baseband interface",
        detail="Requires root access or vendor tools, which this application does not use.",
    ),
    Capability(
        name="RF samples and spectrum",
        access=AccessMethod.UNAVAILABLE,
        source=None,
        detail="A phone is not an SDR and does not expose received samples.",
    ),
)


class AndroidADBReceiver(BaseReceiver):
    """An Android phone reached through ADB."""

    def __init__(self, adb: AdbClient, serial: str) -> None:
        self._adb = adb
        self._serial = serial
        self._identified = False
        self._info = ReceiverInfo(
            receiver_id=self.receiver_id_for(serial),
            kind=ReceiverKind.ANDROID_ADB,
            identifier=serial,
            state=ConnectionState.DISCONNECTED,
        )

    @staticmethod
    def receiver_id_for(serial: str) -> str:
        """The receiver identifier used for the device with this ADB serial."""
        return f"{ReceiverKind.ANDROID_ADB.value}:{serial}"

    @property
    def info(self) -> ReceiverInfo:
        return self._info

    def refresh(self) -> ReceiverInfo:
        for device in self._adb.devices():
            if device.serial == self._serial:
                return self.update(device)
        self._info = self._info.model_copy(
            update={"state": ConnectionState.DISCONNECTED, "state_detail": None}
        )
        return self._info

    def update(self, device: AdbDevice) -> ReceiverInfo:
        """Apply an entry from the ADB device list; identify the phone once it is ready."""
        state = _STATES.get(device.state, ConnectionState.UNAVAILABLE)
        changes: dict[str, object] = {
            "state": state,
            "state_detail": device.state if state is ConnectionState.UNAVAILABLE else None,
        }
        if state is ConnectionState.READY and not self._identified:
            try:
                changes.update(_identity(self._adb.getprops(self._serial)))
                self._identified = True
            except AdbError as exc:
                # Leave the identity unknown; the next update tries again.
                logger.warning(
                    "Could not identify device: %s", exc, extra={"serial": self._serial}
                )
        self._info = self._info.model_copy(update=changes)
        return self._info

    def inspect_capabilities(self) -> CapabilityReport:
        if self._info.state is not ConnectionState.READY:
            raise ReceiverError(
                f"{self._info.display_name} is not ready (state: {self._info.state.value})"
            )
        properties = self._adb.getprops(self._serial)
        registry = self._adb.shell(self._serial, _REGISTRY_COMMAND)
        capabilities = (
            *(_property_capability(name, key, properties) for name, key in _TELEPHONY_PROPERTIES),
            *(_registry_capability(*field, registry) for field in _REGISTRY_FIELDS),
            _cell_identity_capability(registry),
            *_NOT_OBTAINABLE,
        )
        return CapabilityReport(
            receiver_id=self._info.receiver_id,
            inspected_at=datetime.now(timezone.utc),
            capabilities=capabilities,
        )


def _identity(properties: dict[str, str]) -> dict[str, str | None]:
    manufacturer = properties.get("ro.product.manufacturer") or None
    if manufacturer and manufacturer.islower():
        manufacturer = manufacturer.capitalize()  # e.g. "samsung" -> "Samsung"

    release = properties.get("ro.build.version.release")
    sdk = properties.get("ro.build.version.sdk")
    version = f"Android {release}" if release else None
    if version and sdk:
        version += f" (API {sdk})"

    return {
        "manufacturer": manufacturer,
        "model": properties.get("ro.product.model") or None,
        "software_version": version,
    }


def _property_capability(name: str, key: str, properties: dict[str, str]) -> Capability:
    value = properties.get(key, "")
    source = f"getprop {key}"
    # Dual-SIM phones report one comma-separated value per slot.
    if any(part.strip() for part in value.split(",")):
        return Capability(
            name=name,
            access=AccessMethod.DEVICE_DIAGNOSTICS,
            source=source,
            detail=f"Reported: {value}",
        )
    return Capability(
        name=name,
        access=AccessMethod.UNAVAILABLE,
        source=source,
        detail="The property is not set on this phone.",
    )


def _registry_capability(
    name: str, key: str, populated: re.Pattern[str] | None, registry: str
) -> Capability:
    source = f"{_REGISTRY_COMMAND}: {key}"
    values = [
        match.group(1).strip()
        for match in re.finditer(rf"^\s*{re.escape(key)}=(.*)$", registry, re.MULTILINE)
    ]
    if any(
        value not in _EMPTY_VALUES and (populated is None or populated.search(value))
        for value in values
    ):
        return Capability(
            name=name,
            access=AccessMethod.DEVICE_DIAGNOSTICS,
            source=source,
            detail="Present and populated.",
        )
    detail = (
        "Present but empty at the time of inspection."
        if values
        else "Not present in the diagnostic output."
    )
    return Capability(name=name, access=AccessMethod.UNAVAILABLE, source=source, detail=detail)


def _cell_identity_capability(registry: str) -> Capability:
    name = "Cell identity and area code"
    source = f"{_REGISTRY_COMMAND}: CellIdentity"
    values = set(_CELL_IDENTITY.findall(registry))
    if any(value.isdigit() and value != _UNAVAILABLE_NUMBER for value in values):
        return Capability(
            name=name,
            access=AccessMethod.DEVICE_DIAGNOSTICS,
            source=source,
            detail="Present and readable.",
        )
    detail = (
        "Android masks these values in its diagnostic output."
        if _MASKED in values
        else "Not present in the diagnostic output."
    )
    return Capability(name=name, access=AccessMethod.UNAVAILABLE, source=source, detail=detail)
