"""What just happened in Nexview, as something an automation can wait for.

⚠️ **Event entities, not bus events.** Home Assistant's own guidance for 2026
is unambiguous: an integration publishes occurrences as event entities. They
show up in the automation editor, they keep a history, and they need no
template to read. A raw bus event is for payloads too free or too frequent for
an entity, and neither applies here.

⚠️ **Three, split by subject.** One entity for everything - the way the Seerr
integration does it - means every automation has to check first whether the
event it just woke up for was even its own. Somebody who cares about requests
should not be woken by a storage message.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    EVENT_OPERATIONS,
    EVENT_REQUESTS,
    EVENT_STORAGE,
    EVENT_TYPES,
)
from .coordinator import NexviewConfigEntry, NexviewCoordinator
from .entity import NexviewEntity
from .webhook import signal_event

#: ⚠️ **No limit needed.** Every entity here reads from one shared poll, so
#: there is nothing to serialise - Home Assistant asks for this to be stated
#: rather than assumed.
PARALLEL_UPDATES = 0

DESCRIPTIONS: tuple[EventEntityDescription, ...] = (
    EventEntityDescription(
        key=EVENT_REQUESTS,
        translation_key=EVENT_REQUESTS,
        event_types=EVENT_TYPES[EVENT_REQUESTS],
    ),
    EventEntityDescription(
        key=EVENT_STORAGE,
        translation_key=EVENT_STORAGE,
        event_types=EVENT_TYPES[EVENT_STORAGE],
    ),
    EventEntityDescription(
        key=EVENT_OPERATIONS,
        translation_key=EVENT_OPERATIONS,
        event_types=EVENT_TYPES[EVENT_OPERATIONS],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NexviewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        NexviewEventEntity(coordinator, description) for description in DESCRIPTIONS
    )


class NexviewEventEntity(NexviewEntity, EventEntity):
    """One subject's worth of Nexview notifications."""

    entity_description: EventEntityDescription

    def __init__(
        self, coordinator: NexviewCoordinator, description: EventEntityDescription
    ) -> None:
        super().__init__(coordinator, f"event_{description.key}")
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        """⚠️ Subscribe here, and let Home Assistant unsubscribe.

        Wiring this up in ``__init__`` would leave a listener behind every time
        the entry reloads, and each reload would then fire one more time than
        the last.
        """
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_event(self.coordinator.config_entry.entry_id),
                self._incoming,
            )
        )

    @callback
    def _incoming(self, group: str, event_type: str, data: dict[str, Any]) -> None:
        if group != self.entity_description.key:
            return
        self._trigger_event(event_type, data)
        self.async_write_ha_state()
