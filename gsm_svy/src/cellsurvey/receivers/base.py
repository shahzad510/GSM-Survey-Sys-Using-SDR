"""Hardware-independent receiver interface and metadata models.

Every measurement source (an Android phone today, SDR hardware later)
implements :class:`BaseReceiver` and describes itself with the models here,
so the rest of the application never depends on a particular device.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from pydantic import AwareDatetime, BaseModel, ConfigDict


class ReceiverError(Exception):
    """A receiver could not be reached or could not carry out a request."""


class ReceiverKind(str, Enum):
    """How a receiver is attached and driven."""

    ANDROID_ADB = "android_adb"


class ConnectionState(str, Enum):
    """Whether a detected receiver can be used."""

    READY = "ready"
    """Attached and usable."""
    UNAUTHORIZED = "unauthorized"
    """Attached, but access has not been authorized on the device."""
    OFFLINE = "offline"
    """Attached, but not responding."""
    NO_PERMISSIONS = "no_permissions"
    """Attached, but this computer lacks permission to open it."""
    UNAVAILABLE = "unavailable"
    """Attached in a mode that cannot be used (see ``state_detail``)."""
    DISCONNECTED = "disconnected"
    """No longer attached."""


class AccessMethod(str, Enum):
    """How a piece of data is obtained from a receiver, if at all.

    Recorded so that reports can state the provenance of every value.
    """

    DOCUMENTED_API = "documented_api"
    """Obtained through a documented, public programming interface."""
    DEVICE_DIAGNOSTICS = "device_diagnostics"
    """Obtained through diagnostics the device owner has authorized.

    These report what the device chooses to expose; their output format is not
    a stable contract.
    """
    UNAVAILABLE = "unavailable"
    """Not obtainable from this receiver as it is currently used."""


class ReceiverInfo(BaseModel):
    """Standardized receiver metadata. Unknown fields are ``None``."""

    model_config = ConfigDict(frozen=True)

    receiver_id: str
    """Stable identifier, unique across receiver kinds."""
    kind: ReceiverKind
    identifier: str
    """Hardware identifier as reported by the connection (e.g. ADB serial)."""
    state: ConnectionState
    state_detail: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    software_version: str | None = None

    @property
    def display_name(self) -> str:
        """Manufacturer and model when known, otherwise the identifier."""
        name = " ".join(part for part in (self.manufacturer, self.model) if part)
        return name or self.identifier


class Capability(BaseModel):
    """One kind of data and how (or whether) the receiver provides it."""

    model_config = ConfigDict(frozen=True)

    name: str
    access: AccessMethod
    source: str | None = None
    """The interface the data comes from, or would come from."""
    detail: str
    """What was found, or why the data is unavailable."""


class CapabilityReport(BaseModel):
    """Result of inspecting what a receiver exposes."""

    model_config = ConfigDict(frozen=True)

    receiver_id: str
    inspected_at: AwareDatetime
    capabilities: tuple[Capability, ...]


class BaseReceiver(ABC):
    """Common interface for all measurement receivers.

    Measurement acquisition is added to this interface in Milestone 3, together
    with the common measurement schema.
    """

    @property
    @abstractmethod
    def info(self) -> ReceiverInfo:
        """Metadata as of the last :meth:`refresh`."""

    @abstractmethod
    def refresh(self) -> ReceiverInfo:
        """Re-read the connection state and identity from the hardware.

        Raises:
            ReceiverError: the connection layer itself failed.
        """

    @abstractmethod
    def inspect_capabilities(self) -> CapabilityReport:
        """Probe which data the receiver exposes, without changing the device.

        Raises:
            ReceiverError: the receiver is not ready or stopped responding.
        """
