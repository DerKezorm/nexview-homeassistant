"""What every Nexview entity has in common.

⚠️ **One device, described as a service.** Nexview is not a box on a shelf, and
saying so keeps it out of the area picker where it would only be in the way.
The link back to its own web interface sits on the device page, which is where
somebody looks when they want to see the thing itself.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import AccountUsage, Instance, MediaServer
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


class NexviewInstanceEntity(NexviewEntity):
    """Something about one Radarr or Sonarr behind Nexview.

    ⚠️ **Its own device, hanging off Nexview.** Home Assistant then draws the
    chain as it really is, and somebody with four instances gets four tidy
    cards instead of forty sensors in one list.
    """

    def __init__(
        self, coordinator: NexviewCoordinator, instance_key: str, key: str
    ) -> None:
        super().__init__(coordinator, f"{instance_key}_{key}")
        self.instance_key = instance_key
        entry = coordinator.config_entry
        instance = coordinator.data.instances.get(instance_key)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{instance_key}")},
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="nexapps",
            # "radarr-standard" and "sonarr-uhd" say which product and which
            # tier, and that is exactly what belongs in the model line.
            model=instance_key.split("-")[0].capitalize() if instance_key else None,
            name=instance.name if instance else instance_key,
            sw_version=instance.version if instance else None,
        )
        _haenge_unter(self._attr_device_info, coordinator)

    @property
    def instance(self) -> Instance | None:
        """The current state of this instance, or ``None`` if it is gone."""
        return self.coordinator.data.instances.get(self.instance_key)

    @property
    def available(self) -> bool:
        """⚠️ Gone from Nexview is unavailable, not deleted.

        An instance that disappears for a moment - somebody is editing the
        settings - must not take its history with it. It comes back with the
        same entities.
        """
        return super().available and self.instance is not None


class NexviewAccountEntity(NexviewEntity):
    """Something about one Nexview account.

    ⚠️ **Name and figures, nothing else.** A device here carries the display
    name because a card without one is useless, and nothing beyond it: no mail
    address, no linked media server account, no avatar. Home Assistant keeps
    what it is given, and keeps it for years.
    """

    def __init__(
        self, coordinator: NexviewCoordinator, user_id: int, key: str
    ) -> None:
        super().__init__(coordinator, f"account{user_id}_{key}")
        self.user_id = user_id
        entry = coordinator.config_entry
        account = coordinator.data.accounts.get(user_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_account{user_id}")},
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="nexapps",
            model="Account",
            name=account.name if account else f"Account {user_id}",
        )
        _haenge_unter(self._attr_device_info, coordinator)

    @property
    def account(self) -> AccountUsage | None:
        return self.coordinator.data.accounts.get(self.user_id)

    @property
    def available(self) -> bool:
        return super().available and self.account is not None


class NexviewServerEntity(NexviewEntity):
    """Something about one Plex, Jellyfin or Emby.

    ⚠️ **The media servers are not Nexview's, and the device says so.** They
    belong to whoever runs them; Nexview only talks to them. Hanging them off
    Nexview is still right - that is how they got here - but the manufacturer
    line names the product, not nexapps.
    """

    def __init__(
        self, coordinator: NexviewCoordinator, server_key: str, key: str
    ) -> None:
        super().__init__(coordinator, f"server{server_key}_{key}")
        self.server_key = server_key
        entry = coordinator.config_entry
        server = coordinator.data.servers.get(server_key)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_server{server_key}")},
            entry_type=DeviceEntryType.SERVICE,
            manufacturer=(server.provider.capitalize() if server else None),
            model="Media server",
            name=server.name if server else f"Server {server_key}",
        )
        _haenge_unter(self._attr_device_info, coordinator)

    @property
    def server(self) -> MediaServer | None:
        return self.coordinator.data.servers.get(self.server_key)

    @property
    def available(self) -> bool:
        return super().available and self.server is not None


def _haenge_unter(info: DeviceInfo, coordinator: NexviewCoordinator) -> None:
    """Dieses Gerät unter Nexview hängen, sobald es das Hauptgerät gibt.

    ⚠️ **Nachträglich gesetzt, nicht im Aufruf.** ``via_device_id`` will eine
    Zeichenkette, und in der einen Sekunde zwischen erstem Abruf und
    angelegtem Hauptgerät gibt es noch keine. Ein Kindgerät hängt dann lieber
    für einen Moment frei, als dass seine Registrierung an einem None
    scheitert.
    """
    kennung = coordinator.main_device_id
    if kennung:
        info["via_device_id"] = kennung
