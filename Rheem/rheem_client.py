#!/usr/bin/env python3
"""Rheem EcoNet water heater client.

Wraps the unofficial `pyeconet` library (ClearBlade cloud at
rheem.clearblade.com) in a small sync-friendly surface for the monitor.
Auth is plain email/password -> bearer `user_token` (no 2FA).

The API factory is injectable so tests can supply a fake EcoNet api without
patching production code.

Hot water availability is reported by the tank as discrete levels:
    0   = empty
    33  = "1/3rd full"
    66  = "2/3rd full"
    100 = full
Some tanks do not report `@HOTWATER` at all, in which case availability is None.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from pyeconet import EcoNetApiInterface
from pyeconet.errors import InvalidCredentialsError, PyeconetError
from pyeconet.equipment import EquipmentType

from lib.logger import get_logger


class RheemAuthError(Exception):
    """EcoNet authentication failed."""


class RheemAPIError(Exception):
    """EcoNet API request error."""


@dataclass
class WaterHeaterStatus:
    """Snapshot of one water heater's relevant telemetry."""

    serial_number: str
    name: str
    availability: Optional[int]
    running: bool
    set_point: Optional[int]
    connected: bool


# A factory that returns an already-logged-in EcoNet api instance.
ApiFactory = Callable[[], Awaitable[EcoNetApiInterface]]


class RheemClient:
    """EcoNet client exposing water heater telemetry."""

    def __init__(
        self,
        email: str,
        password: str,
        api_factory: Optional[ApiFactory] = None,
    ) -> None:
        self.email = email
        self.password = password
        self._api: Optional[EcoNetApiInterface] = None
        self._api_factory: ApiFactory = api_factory or self._default_factory
        self.logger = get_logger(__name__)

    def _default_factory(self) -> Awaitable[EcoNetApiInterface]:
        return EcoNetApiInterface.login(self.email, self.password)  # type: ignore[no-any-return]

    async def _ensure_api(self) -> EcoNetApiInterface:
        if self._api is not None:
            return self._api
        try:
            self._api = await self._api_factory()
        except InvalidCredentialsError as e:
            raise RheemAuthError(f"EcoNet login failed (invalid credentials): {e}") from e
        except PyeconetError as e:
            raise RheemAPIError(f"EcoNet login error: {e}") from e
        return self._api

    async def get_water_heaters(self) -> list[WaterHeaterStatus]:
        """Return telemetry for all water heaters on the account."""
        api = await self._ensure_api()
        try:
            equipment = await api.get_equipment_by_type([EquipmentType.WATER_HEATER])
        except PyeconetError as e:
            raise RheemAPIError(f"EcoNet equipment fetch failed: {e}") from e

        heaters = equipment.get(EquipmentType.WATER_HEATER, [])
        return [self._to_status(h) for h in heaters]

    @staticmethod
    def _to_status(heater: Any) -> WaterHeaterStatus:
        avail = heater.tank_hot_water_availability
        set_point: Optional[int] = None
        try:
            set_point = heater.set_point
        except (KeyError, TypeError):
            pass
        return WaterHeaterStatus(
            serial_number=heater.serial_number,
            name=heater.device_name,
            availability=avail,
            running=bool(heater.running),
            set_point=set_point,
            connected=bool(heater.connected),
        )


__all__ = [
    "RheemClient",
    "WaterHeaterStatus",
    "RheemAuthError",
    "RheemAPIError",
]
