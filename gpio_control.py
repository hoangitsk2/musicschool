"""GPIO relay control abstraction with safe fallbacks."""
from __future__ import annotations

import logging
from typing import Optional

try:
    import RPi.GPIO as GPIO  # type: ignore
except Exception:  # pragma: no cover - executed on non-RPi systems
    GPIO = None  # type: ignore


class RelayController:
    """Control a relay to power external hardware."""

    def __init__(self, enabled: bool, relay_pin: int = 17, active_high: bool = True) -> None:
        self.enabled = enabled and GPIO is not None
        self.relay_pin = relay_pin
        self.active_high = active_high
        self._last_state: Optional[bool] = None
        if self.enabled:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.relay_pin, GPIO.OUT)
            self.power_off()
        else:
            logging.getLogger(__name__).info("RelayController running in mock mode")

    def _write(self, state: bool) -> None:
        if not self.enabled:
            self._last_state = state
            return
        GPIO.output(self.relay_pin, GPIO.HIGH if state else GPIO.LOW)
        self._last_state = state

    def power_on(self) -> None:
        desired = self.active_high
        self._write(desired)

    def power_off(self) -> None:
        desired = not self.active_high
        self._write(desired)

    def cleanup(self) -> None:
        if self.enabled and GPIO is not None:
            GPIO.cleanup(self.relay_pin)

    @property
    def is_power_on(self) -> bool:
        if self._last_state is None:
            return False
        return self._last_state == self.active_high


__all__ = ["RelayController"]
