from __future__ import annotations

import pytest

from cellsurvey.receivers.adb import (
    AdbClient,
    AdbDevice,
    AdbError,
    AdbNotFoundError,
    parse_devices,
    parse_getprop,
)
from fakes import DEVICES_NONE, DEVICES_READY, SERIAL


def test_parse_no_devices() -> None:
    assert parse_devices(DEVICES_NONE) == []


def test_parse_ready_device_with_properties() -> None:
    (device,) = parse_devices(DEVICES_READY)

    assert device.serial == SERIAL
    assert device.state == "device"
    assert device.properties["model"] == "SM_A600F"
    assert device.properties["transport_id"] == "7"


def test_parse_mixed_states_and_ignores_text_before_header() -> None:
    output = (
        "* daemon not running; starting now at tcp:5037\n"
        "* daemon started successfully\n"
        "List of devices attached\n"
        "AAA111\tunauthorized usb:1-3 transport_id:2\n"
        "BBB222\toffline\n"
        "????????????\tno permissions (user in plugdev group; are your udev rules wrong?); "
        "see [http://developer.android.com/tools/device.html]\n"
        "CCC333\trecovery\n"
    )

    assert parse_devices(output) == [
        AdbDevice("AAA111", "unauthorized", {"usb": "1-3", "transport_id": "2"}),
        AdbDevice("BBB222", "offline"),
        AdbDevice("????????????", "no permissions"),
        AdbDevice("CCC333", "recovery"),
    ]


def test_parse_devices_rejects_unexpected_output() -> None:
    with pytest.raises(AdbError):
        parse_devices("error: something else entirely\n")


def test_parse_getprop() -> None:
    output = "[ro.product.model]: [SM-A600F]\n[gsm.sim.state]: []\nnot a property line\n"

    assert parse_getprop(output) == {"ro.product.model": "SM-A600F", "gsm.sim.state": ""}


def test_missing_executable_raises_not_found() -> None:
    with pytest.raises(AdbNotFoundError):
        AdbClient(executable="/nonexistent/adb").run(["devices"])


def test_adb_absent_from_path_raises_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")

    with pytest.raises(AdbNotFoundError, match="sudo apt install adb"):
        AdbClient().run(["devices"])


def test_failing_command_raises_adb_error() -> None:
    with pytest.raises(AdbError, match="exit status 1"):
        AdbClient(executable="/bin/false").run(["devices"])


def test_slow_command_times_out() -> None:
    with pytest.raises(AdbError, match="timed out"):
        AdbClient(executable="/bin/sleep", timeout=0.1).run(["5"])


def test_serial_is_passed_before_the_command() -> None:
    assert AdbClient(executable="/bin/echo").shell("ABC", "getprop") == "-s ABC shell getprop\n"
