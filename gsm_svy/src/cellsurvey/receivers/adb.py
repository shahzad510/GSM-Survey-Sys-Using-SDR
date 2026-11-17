"""Thin wrapper around the Android Debug Bridge (``adb``) command-line tool.

Only read-only commands are issued. Nothing here uses root access.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field

from cellsurvey.receivers.base import ReceiverError

_DEVICES_HEADER = "List of devices attached"
_NO_PERMISSIONS = "no permissions"
_GETPROP_LINE = re.compile(r"^\[(.+?)\]: \[(.*)\]$")


class AdbError(ReceiverError):
    """An adb command failed or timed out."""


class AdbNotFoundError(AdbError):
    """The adb executable is not installed or not at the configured path."""


@dataclass(frozen=True)
class AdbDevice:
    """One line of ``adb devices -l``."""

    serial: str
    state: str
    """Raw adb state, e.g. ``device``, ``unauthorized``, ``offline``."""
    properties: dict[str, str] = field(default_factory=dict)
    """Extra ``key:value`` fields such as ``model`` and ``transport_id``."""


def parse_devices(output: str) -> list[AdbDevice]:
    """Parse the output of ``adb devices -l``."""
    lines = output.splitlines()
    try:
        start = lines.index(_DEVICES_HEADER) + 1
    except ValueError as exc:
        raise AdbError(f"Unexpected output from 'adb devices': {output.strip()!r}") from exc

    devices = []
    for line in lines[start:]:
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        serial, rest = parts
        if rest.startswith(_NO_PERMISSIONS):
            # The state is followed by free text explaining the udev problem.
            devices.append(AdbDevice(serial, _NO_PERMISSIONS))
            continue
        state, *extras = rest.split()
        properties = dict(extra.split(":", 1) for extra in extras if ":" in extra)
        devices.append(AdbDevice(serial, state, properties))
    return devices


def parse_getprop(output: str) -> dict[str, str]:
    """Parse ``getprop`` output (``[key]: [value]`` lines) into a dictionary."""
    properties = {}
    for line in output.splitlines():
        match = _GETPROP_LINE.match(line.strip())
        if match:
            properties[match.group(1)] = match.group(2)
    return properties


class AdbClient:
    """Runs adb commands and returns their standard output."""

    def __init__(self, executable: str | None = None, timeout: float = 10.0) -> None:
        """
        Args:
            executable: path to adb; when ``None`` it is looked up on ``PATH``.
            timeout: seconds to wait for any single command.
        """
        self._executable = executable
        self._timeout = timeout

    def run(self, args: Sequence[str], serial: str | None = None) -> str:
        """Run ``adb [-s serial] args`` and return standard output.

        Raises:
            AdbNotFoundError: adb is not installed.
            AdbError: the command failed or timed out.
        """
        executable = self._executable or shutil.which("adb")
        if executable is None:
            raise AdbNotFoundError("adb was not found. Install it with: sudo apt install adb")
        command = [executable, *(["-s", serial] if serial else []), *args]
        description = "adb " + " ".join(args)
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self._timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AdbNotFoundError(f"adb was not found at {executable}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"'{description}' timed out after {self._timeout:g} s") from exc
        except OSError as exc:
            raise AdbError(f"'{description}' could not be run: {exc}") from exc
        if completed.returncode != 0:
            reason = completed.stderr.strip() or f"exit status {completed.returncode}"
            raise AdbError(f"'{description}' failed: {reason}")
        return completed.stdout

    def devices(self) -> list[AdbDevice]:
        """List attached devices. Starts the adb server if it is not running."""
        return parse_devices(self.run(["devices", "-l"]))

    def shell(self, serial: str, command: str) -> str:
        """Run a shell command on the device as the unprivileged ``shell`` user."""
        return self.run(["shell", command], serial)

    def getprops(self, serial: str) -> dict[str, str]:
        """Read the device's system properties."""
        return parse_getprop(self.shell(serial, "getprop"))
