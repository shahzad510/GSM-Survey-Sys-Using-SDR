from __future__ import annotations

import pytest

from cellsurvey.receivers.adb import AdbDevice, AdbError
from cellsurvey.receivers.android import AndroidADBReceiver
from cellsurvey.receivers.base import (
    AccessMethod,
    Capability,
    ConnectionState,
    ReceiverError,
    ReceiverKind,
)
from fakes import (
    DEVICES_NONE,
    DEVICES_READY,
    DEVICES_UNAUTHORIZED,
    GETPROP,
    REGISTRY_SLOT_1,
    SERIAL,
    FakeAdb,
)


def _ready_receiver(adb: FakeAdb) -> AndroidADBReceiver:
    receiver = AndroidADBReceiver(adb, SERIAL)
    receiver.refresh()
    return receiver


def _by_name(capabilities: tuple[Capability, ...]) -> dict[str, Capability]:
    return {capability.name: capability for capability in capabilities}


def test_ready_device_is_identified() -> None:
    info = _ready_receiver(FakeAdb(DEVICES_READY)).info

    assert info.receiver_id == f"android_adb:{SERIAL}"
    assert info.kind is ReceiverKind.ANDROID_ADB
    assert info.state is ConnectionState.READY
    assert info.manufacturer == "Samsung"
    assert info.model == "SM-A600F"
    assert info.software_version == "Android 10 (API 29)"
    assert info.display_name == "Samsung SM-A600F"


def test_identity_is_read_only_once() -> None:
    adb = FakeAdb(DEVICES_READY)
    receiver = _ready_receiver(adb)
    receiver.refresh()

    assert adb.shell_calls() == ["getprop"]


def test_unauthorized_device_is_not_queried_and_has_no_identity() -> None:
    adb = FakeAdb(DEVICES_UNAUTHORIZED)
    info = _ready_receiver(adb).info

    assert info.state is ConnectionState.UNAUTHORIZED
    assert info.model is None
    assert info.display_name == SERIAL
    assert adb.shell_calls() == []


def test_missing_identity_properties_stay_unknown() -> None:
    info = _ready_receiver(FakeAdb(DEVICES_READY, {"getprop": ""})).info

    assert info.state is ConnectionState.READY
    assert (info.manufacturer, info.model, info.software_version) == (None, None, None)


def test_unrecognised_adb_state_is_unavailable_with_detail() -> None:
    receiver = AndroidADBReceiver(FakeAdb(), SERIAL)

    info = receiver.update(AdbDevice(SERIAL, "recovery"))

    assert info.state is ConnectionState.UNAVAILABLE
    assert info.state_detail == "recovery"


def test_device_that_disappears_is_disconnected_but_keeps_identity() -> None:
    adb = FakeAdb(DEVICES_READY)
    receiver = _ready_receiver(adb)
    adb.devices_output = DEVICES_NONE

    info = receiver.refresh()

    assert info.state is ConnectionState.DISCONNECTED
    assert info.model == "SM-A600F"


def test_identification_failure_is_retried_on_next_update() -> None:
    class FlakyAdb(FakeAdb):
        fail_shell = True

        def run(self, args, serial=None):  # type: ignore[no-untyped-def]
            if args[0] == "shell" and self.fail_shell:
                raise AdbError("device offline")
            return super().run(args, serial)

    adb = FlakyAdb(DEVICES_READY)
    receiver = _ready_receiver(adb)
    assert receiver.info.state is ConnectionState.READY
    assert receiver.info.model is None

    adb.fail_shell = False
    assert receiver.refresh().model == "SM-A600F"


def test_capabilities_separate_diagnostics_from_unavailable_data() -> None:
    report = _ready_receiver(FakeAdb(DEVICES_READY)).inspect_capabilities()
    capabilities = _by_name(report.capabilities)

    assert report.receiver_id == f"android_adb:{SERIAL}"
    assert report.inspected_at.utcoffset() is not None
    for name in (
        "Network technology",
        "Operator name",
        "Operator MCC and MNC",
        "Service state",
        "Signal strength",
        "Cell information",
    ):
        assert capabilities[name].access is AccessMethod.DEVICE_DIAGNOSTICS, name
    for name in (
        "Cell identity and area code",
        "Android telephony API",
        "Raw modem diagnostics",
        "RF samples and spectrum",
    ):
        assert capabilities[name].access is AccessMethod.UNAVAILABLE, name
    assert capabilities["Network technology"].detail == "Reported: HSPAP,Unknown"
    assert capabilities["Operator MCC and MNC"].detail == "Reported: 00101"
    assert capabilities["Cell identity and area code"].detail == (
        "Android masks these values in its diagnostic output."
    )
    # ADB alone never yields documented-API data, and the report must not claim it.
    assert all(c.access is not AccessMethod.DOCUMENTED_API for c in report.capabilities)


@pytest.mark.parametrize(
    ("registry", "detail"),
    [
        ("  mCellInfo=null\n", "Present but empty at the time of inspection."),
        ("  mCellInfo=[]\n", "Present but empty at the time of inspection."),
        ("  mCallState=0\n", "Not present in the diagnostic output."),
    ],
    ids=["null", "empty-list", "absent"],
)
def test_empty_or_absent_cell_information_is_unavailable(registry: str, detail: str) -> None:
    adb = FakeAdb(DEVICES_READY, {"getprop": GETPROP, "dumpsys telephony.registry": registry})

    capability = _by_name(_ready_receiver(adb).inspect_capabilities().capabilities)[
        "Cell information"
    ]

    assert capability.access is AccessMethod.UNAVAILABLE
    assert capability.detail == detail


def test_slot_without_service_exposes_no_signal_or_cell_data() -> None:
    adb = FakeAdb(
        DEVICES_READY, {"getprop": GETPROP, "dumpsys telephony.registry": REGISTRY_SLOT_1}
    )

    capabilities = _by_name(_ready_receiver(adb).inspect_capabilities().capabilities)

    # The slot still prints a signal-strength record, but every technology is "Invalid".
    assert capabilities["Signal strength"].access is AccessMethod.UNAVAILABLE
    assert capabilities["Cell information"].access is AccessMethod.UNAVAILABLE
    assert capabilities["Cell identity and area code"].detail == (
        "Not present in the diagnostic output."
    )
    # "Out of service" is itself a service state.
    assert capabilities["Service state"].access is AccessMethod.DEVICE_DIAGNOSTICS


@pytest.mark.parametrize(
    ("identity", "access"),
    [
        ("mLac=1234 mCid=567890", AccessMethod.DEVICE_DIAGNOSTICS),
        ("mLac=2147483647 mCid=2147483647", AccessMethod.UNAVAILABLE),
        ("mLac=<MASKED> mCid=<MASKED>", AccessMethod.UNAVAILABLE),
    ],
    ids=["readable", "not-available-sentinel", "masked"],
)
def test_cell_identity_is_available_only_when_readable(
    identity: str, access: AccessMethod
) -> None:
    registry = f"    mCellInfo=[CellInfoWcdma:{{CellIdentityWcdma:{{ {identity} mPsc=1}}}}]\n"
    adb = FakeAdb(DEVICES_READY, {"getprop": GETPROP, "dumpsys telephony.registry": registry})

    capability = _by_name(_ready_receiver(adb).inspect_capabilities().capabilities)[
        "Cell identity and area code"
    ]

    assert capability.access is access


@pytest.mark.parametrize("value", ["", ",", " , "], ids=["empty", "dual-sim-empty", "blank"])
def test_unset_property_is_unavailable(value: str) -> None:
    props = GETPROP.replace("[HSPAP,Unknown]", f"[{value}]")
    assert props != GETPROP
    adb = FakeAdb(DEVICES_READY, {"getprop": props, "dumpsys telephony.registry": ""})

    capability = _by_name(_ready_receiver(adb).inspect_capabilities().capabilities)[
        "Network technology"
    ]

    assert capability.access is AccessMethod.UNAVAILABLE


def test_inspecting_a_receiver_that_is_not_ready_fails() -> None:
    adb = FakeAdb(DEVICES_UNAUTHORIZED)
    receiver = _ready_receiver(adb)

    with pytest.raises(ReceiverError, match="not ready"):
        receiver.inspect_capabilities()
    assert adb.shell_calls() == []
