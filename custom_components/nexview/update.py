"""Nexview in the same list as everything else waiting to be updated.

⚠️ **Shows, does not install.** Nexview runs in a container, and updating it
means pulling an image and recreating it - something the operator does with
their own tooling. An install button here would either lie or need access to
the Docker socket, and neither is worth it. What this does is make sure Nexview
does not sit at an old version for months because nobody happened to look.
"""

from __future__ import annotations

import logging

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import NexviewError
from .coordinator import NexviewConfigEntry, NexviewCoordinator
from .entity import NexviewEntity

#: ⚠️ **No limit needed.** Every entity here reads from one shared poll, so
#: there is nothing to serialise - Home Assistant asks for this to be stated
#: rather than assumed.
PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NexviewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([NexviewUpdate(entry.runtime_data)])


class NexviewUpdate(NexviewEntity, UpdateEntity):
    """Which version is installed, and whether a newer one exists."""

    _attr_translation_key = "nexview"
    _attr_supported_features = UpdateEntityFeature.RELEASE_NOTES

    def __init__(self, coordinator: NexviewCoordinator) -> None:
        super().__init__(coordinator, "update")

    @property
    def installed_version(self) -> str | None:
        version = self.coordinator.data.version
        # Falls back to what the identity call already knows, so this is never
        # empty just because the about endpoint had a bad moment.
        return version.installed if version else self.coordinator.data.identity.version

    @property
    def latest_version(self) -> str | None:
        version = self.coordinator.data.version
        if version is None:
            return None
        # ⚠️ Equal to installed when nothing is pending. Returning None would
        # make Home Assistant show "unknown" rather than "up to date".
        return version.latest if version.update_available else self.installed_version

    @property
    def release_url(self) -> str | None:
        version = self.coordinator.data.version
        return version.release_url if version else None

    async def async_release_notes(self) -> str | None:
        """What changed, as Nexview publishes it.

        Nexview does not serve its own notes, so this points at the release
        page rather than inventing a summary nobody wrote.
        """
        version = self.coordinator.data.version
        if version is None or not version.update_available:
            return None
        if version.release_url:
            return f"[Release notes for {version.latest}]({version.release_url})"
        return None

    async def async_update(self) -> None:
        """Ask Nexview to look for a new version now rather than at its own pace."""
        try:
            await self.coordinator.client.check_update()
        except NexviewError as err:
            _LOGGER.debug("Nexview could not check for updates: %s", err)
        await self.coordinator.async_request_refresh()
