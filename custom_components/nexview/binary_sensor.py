"""Two yes-or-no answers: is Nexview there, and does it call us.

The second one is diagnostic. Nobody automates on it, but when events do not
arrive it is the first thing to look at, and a repair issue already points at
it in words.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NexviewConfigEntry, NexviewCoordinator
from .entity import NexviewEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NexviewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([NexviewReachable(coordinator), NexviewPushing(coordinator)])


class NexviewReachable(NexviewEntity, BinarySensorEntity):
    """Whether the last poll got an answer."""

    entity_description = BinarySensorEntityDescription(
        key="reachable",
        translation_key="reachable",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    )

    def __init__(self, coordinator: NexviewCoordinator) -> None:
        super().__init__(coordinator, "reachable")

    @property
    def available(self) -> bool:
        """⚠️ Always available, or it could never report a problem.

        Every other entity goes unavailable when Nexview stops answering. This
        one has to stay and say ``off`` - an entity that disappears exactly
        when the thing it watches fails is no use to an automation.
        """
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success


class NexviewPushing(NexviewEntity, BinarySensorEntity):
    """Whether Nexview calls us, or we keep asking."""

    entity_description = BinarySensorEntityDescription(
        key="push_active",
        translation_key="push_active",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    )

    def __init__(self, coordinator: NexviewCoordinator) -> None:
        super().__init__(coordinator, "push_active")

    @property
    def is_on(self) -> bool:
        return self.coordinator.pushing
