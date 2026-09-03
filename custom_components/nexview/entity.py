"""What every Nexview entity has in common.

⚠️ **One device, described as a service.** Nexview is not a box on a shelf, and
saying so keeps it out of the area picker where it would only be in the way.
The link back to its own web interface sits on the device page, which is where
somebody looks when they want to see the thing itself.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NexviewCoordinator


class NexviewEntity(CoordinatorEntity[NexviewCoordinator]):
    """Base for everything this integration puts on screen."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NexviewCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="nexapps",
            name=entry.title,
            # Straight to Nexview itself, in a new tab. Deliberately not
            # embedded in Home Assistant: that would mean Nexview has to allow
            # being framed by other pages, and that protection is worth more
            # than a saved bookmark.
            configuration_url=coordinator.client.url,
            sw_version=coordinator.data.identity.version if coordinator.data else None,
        )
