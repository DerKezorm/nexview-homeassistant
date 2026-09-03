"""The numbers.

⚠️ **Only what the key may actually read.** Every description carries the
capability it needs, and what the key does not have is never created. The
alternative - creating everything and leaving half of it permanently
unavailable - makes a working integration look broken to anyone whose account
is not an administrator.

⚠️ **No lists in attributes.** Home Assistant is retiring that habit; Sonarr's
sensor attributes expire with 2026.9. Where somebody needs the items rather
than the count, that is what an action with response data is for.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import CAP_ADMINISTER, CAP_DECIDE, Snapshot
from .coordinator import NexviewConfigEntry, NexviewCoordinator
from .entity import NexviewEntity


@dataclass(frozen=True, kw_only=True)
class NexviewSensorDescription(SensorEntityDescription):
    """A sensor plus the two things that decide whether it exists at all."""

    #: What the key must be allowed to do for this sensor to make sense.
    requires: str
    #: ``None`` means "no figure right now" - the entity goes unavailable
    #: rather than showing a zero that nobody measured.
    value_fn: Callable[[Snapshot], int | None]


def _pending(snapshot: Snapshot) -> int | None:
    """How many requests wait.

    Two sources on purpose: an administrator's key reads it out of the tile it
    fetches anyway, and a key that may only decide gets the same figure from
    the counter made for exactly that.
    """
    if snapshot.tile is not None:
        return snapshot.tile.pending
    return snapshot.pending_count


SENSORS: tuple[NexviewSensorDescription, ...] = (
    NexviewSensorDescription(
        key="pending_requests",
        translation_key="pending_requests",
        requires=CAP_DECIDE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_pending,
    ),
    NexviewSensorDescription(
        key="processing_requests",
        translation_key="processing_requests",
        requires=CAP_ADMINISTER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.tile.processing if s.tile else None,
    ),
    NexviewSensorDescription(
        key="failed_requests",
        translation_key="failed_requests",
        requires=CAP_ADMINISTER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.tile.failed_7d if s.tile else None,
    ),
    NexviewSensorDescription(
        key="findings_error",
        translation_key="findings_error",
        requires=CAP_ADMINISTER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.tile.findings_error if s.tile else None,
    ),
    NexviewSensorDescription(
        key="findings_warning",
        translation_key="findings_warning",
        requires=CAP_ADMINISTER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.tile.findings_warning if s.tile else None,
    ),
    NexviewSensorDescription(
        key="findings_hint",
        translation_key="findings_hint",
        requires=CAP_ADMINISTER,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.tile.findings_hint if s.tile else None,
    ),
    NexviewSensorDescription(
        key="open_tickets",
        translation_key="open_tickets",
        requires=CAP_ADMINISTER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.tile.open_tickets if s.tile else None,
    ),
    NexviewSensorDescription(
        key="free_space",
        translation_key="free_space",
        requires=CAP_ADMINISTER,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.TERABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.tile.free_bytes if s.tile else None,
    ),
    NexviewSensorDescription(
        key="used_space",
        translation_key="used_space",
        requires=CAP_ADMINISTER,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.TERABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.tile.used_bytes if s.tile else None,
    ),
    NexviewSensorDescription(
        key="movies",
        translation_key="movies",
        requires=CAP_ADMINISTER,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.tile.movies if s.tile else None,
    ),
    NexviewSensorDescription(
        key="series",
        translation_key="series",
        requires=CAP_ADMINISTER,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.tile.series if s.tile else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NexviewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    identity = coordinator.data.identity
    async_add_entities(
        NexviewSensor(coordinator, description)
        for description in SENSORS
        if identity.may(description.requires)
    )


class NexviewSensor(NexviewEntity, SensorEntity):
    entity_description: NexviewSensorDescription

    def __init__(
        self, coordinator: NexviewCoordinator, description: NexviewSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Unavailable when there is no figure, not zero.

        A key can lose a right while Home Assistant runs, and Nexview can
        answer one call and not the next. Showing a zero in either case would
        be a measurement nobody took.
        """
        return super().available and self.native_value is not None
