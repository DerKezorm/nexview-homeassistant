"""The errands an operator runs by hand.

⚠️ **Only the harmless half.** Checking a connection, asking for a storage
reconciliation, acknowledging findings: each of these does something Nexview
would eventually do on its own, just now. Deliberately absent are backups,
restores, blocking accounts and resetting allowances - an automation that
misfires at three in the morning should not be able to reach any of those.

⚠️ **Off by default.** These are for a dashboard somebody deliberately builds,
not for the twelve tiles a new integration greets you with.
"""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any, Final

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import CAP_CONFIGURE, NexviewError
from .const import DOMAIN
from .coordinator import NexviewConfigEntry, NexviewCoordinator
from .entity import NexviewEntity, NexviewInstanceEntity

#: ⚠️ **No limit needed.** Every entity here reads from one shared poll, so
#: there is nothing to serialise - Home Assistant asks for this to be stated
#: rather than assumed.
PARALLEL_UPDATES = 0

#: Nexview names its instances ``radarr-standard`` and its test endpoints
#: ``radarr``. Spelled out rather than derived by string surgery: there are
#: four of them, and a rule that happens to work is harder to check than a
#: table that says so.
SERVICE_FOR: Final[dict[str, str]] = {
    "radarr-standard": "radarr",
    "radarr-uhd": "radarr_uhd",
    "sonarr-standard": "sonarr",
    "sonarr-uhd": "sonarr_uhd",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NexviewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    identity = coordinator.data.identity

    if not identity.may(CAP_CONFIGURE):
        # Every errand here changes something. A key that may only read gets
        # no buttons at all rather than buttons that answer 403.
        return

    async_add_entities(
        [
            NexviewCheckUpdate(coordinator),
            NexviewStorageSync(coordinator),
            NexviewAcknowledge(coordinator),
        ]
    )

    known: set[str] = set()

    @callback
    def _add_new() -> None:
        current = set(coordinator.data.instances)
        known.intersection_update(current)
        neu = [NexviewTestConnection(coordinator, key) for key in current - known]
        known.update(current)
        if neu:
            async_add_entities(neu)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class _NexviewButton(NexviewEntity, ButtonEntity):
    """Shared plumbing: run the errand, then refresh what it changed."""

    async def _run(self, coro: Coroutine[Any, Any, None]) -> None:
        try:
            await coro
        except NexviewError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="request_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


class NexviewCheckUpdate(_NexviewButton):
    entity_description = ButtonEntityDescription(
        key="check_update",
        translation_key="check_update",
        entity_category=EntityCategory.CONFIG,
    )

    def __init__(self, coordinator: NexviewCoordinator) -> None:
        super().__init__(coordinator, "check_update")

    async def async_press(self) -> None:
        await self._run(self.coordinator.client.check_update())


class NexviewStorageSync(_NexviewButton):
    entity_description = ButtonEntityDescription(
        key="storage_sync",
        translation_key="storage_sync",
        entity_category=EntityCategory.CONFIG,
    )

    def __init__(self, coordinator: NexviewCoordinator) -> None:
        super().__init__(coordinator, "storage_sync")

    async def async_press(self) -> None:
        await self._run(self.coordinator.client.storage_sync())


class NexviewAcknowledge(_NexviewButton):
    """Mark the findings as seen, the same as opening the dashboard would."""

    entity_description = ButtonEntityDescription(
        key="acknowledge_findings",
        translation_key="acknowledge_findings",
        entity_category=EntityCategory.CONFIG,
    )

    def __init__(self, coordinator: NexviewCoordinator) -> None:
        super().__init__(coordinator, "acknowledge_findings")

    async def async_press(self) -> None:
        await self._run(self.coordinator.client.acknowledge_findings())


class NexviewTestConnection(NexviewInstanceEntity, ButtonEntity):
    """Ask Nexview to talk to this instance right now."""

    entity_description = ButtonEntityDescription(
        key="test_connection",
        translation_key="test_connection",
        entity_category=EntityCategory.CONFIG,
    )

    def __init__(self, coordinator: NexviewCoordinator, instance_key: str) -> None:
        super().__init__(coordinator, instance_key, "test_connection")

    async def async_press(self) -> None:
        service = SERVICE_FOR.get(self.instance_key)
        if service is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unknown_instance",
                translation_placeholders={"instance": self.instance_key},
            )
        try:
            await self.coordinator.client.test_connection(service)
        except NexviewError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="request_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
