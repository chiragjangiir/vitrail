"""Registre des drivers de provisioning par OS."""

from __future__ import annotations

from .android import AndroidDriver
from .base import Driver, DriverError
from .brightsign import BrightSignDriver
from .ssh import SshDriver
from .windows import WinRmDriver

# os → classe de driver. Linux et RPi partagent le driver SSH (device déjà installé).
DRIVERS: dict[str, type[Driver]] = {
    "android": AndroidDriver,
    "linux": SshDriver,
    "rpi": SshDriver,
    "brightsign": BrightSignDriver,
    "windows": WinRmDriver,
}


def get_driver(os_name: str, payload: dict, opts: dict) -> Driver:
    cls = DRIVERS.get(os_name)
    if cls is None:
        raise DriverError(
            f"OS « {os_name} » non pris en charge par un driver réseau. "
            f"Canaux disponibles : {', '.join(sorted(DRIVERS))}. "
            f"(chromeos/extension = hors périmètre ; greenfield = image USB/SD.)")
    return cls(payload, opts)


__all__ = ["Driver", "DriverError", "get_driver", "DRIVERS"]
