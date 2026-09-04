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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NexviewConfigEntry, NexviewCoordinator
from .entity import NexviewAccountEntity, NexviewEntity, NexviewInstanceEntity

#: ⚠️ **No limit needed.** Every entity here reads from one shared poll, so
#: there is nothing to serialise - Home Assistant asks for this to be stated
#: rather than assumed.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NexviewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        NexviewReachable(coordinator),
        NexviewPushing(coordinator),
    ]
    if coordinator.data.personal is not None:
        entities.append(NexviewMyQuotaExhausted(coordinator))
    async_add_entities(entities)

    known_instances: set[str] = set()
    known_accounts: set[int] = set()

    @callback
    def _add_new() -> None:
        neu: list[BinarySensorEntity] = []

        current = set(coordinator.data.instances)
        known_instances.intersection_update(current)
        for key in current - known_instances:
            neu.append(NexviewInstanceReachable(coordinator, key))
            neu.append(NexviewInstanceWebhook(coordinator, key))
        known_instances.update(current)

        current_accounts = set(coordinator.data.accounts)
        known_accounts.intersection_update(current_accounts)
        neu.extend(
            NexviewQuotaExhausted(coordinator, user_id)
            for user_id in current_accounts - known_accounts
        )
        known_accounts.update(current_accounts)

        if neu:
            async_add_entities(neu)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


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


class NexviewInstanceReachable(NexviewInstanceEntity, BinarySensorEntity):
    """Whether this Radarr or Sonarr answers Nexview."""

    entity_description = BinarySensorEntityDescription(
        key="reachable",
        translation_key="instance_reachable",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    )

    def __init__(self, coordinator: NexviewCoordinator, instance_key: str) -> None:
        super().__init__(coordinator, instance_key, "reachable")

    @property
    def is_on(self) -> bool:
        return bool(self.instance and self.instance.reachable)


class NexviewQuotaExhausted(NexviewAccountEntity, BinarySensorEntity):
    """Whether this account has used up an allowance.

    ⚠️ **Both allowances count, and either one is enough.** Nexview applies
    the number of titles and the storage figure at the same time, so an
    account that has room on one and none on the other cannot request either
    way. One sensor that says "cannot request right now" is the honest answer;
    two separate ones would invite an automation that only checks the wrong
    half.
    """

    entity_description = BinarySensorEntityDescription(
        key="quota_exhausted",
        translation_key="quota_exhausted",
        device_class=BinarySensorDeviceClass.PROBLEM,
    )

    def __init__(self, coordinator: NexviewCoordinator, user_id: int) -> None:
        super().__init__(coordinator, user_id, "quota_exhausted")

    @property
    def is_on(self) -> bool:
        a = self.account
        if a is None:
            return False
        return bool(a.movies.exhausted or a.series.exhausted or a.storage.exhausted)


class NexviewInstanceWebhook(NexviewInstanceEntity, BinarySensorEntity):
    """Whether this Radarr or Sonarr calls Nexview back.

    ⚠️ **Off means slower, not broken, and that is why it needs saying.**
    Without the callback Nexview polls the instance instead, so everything
    still works and downloads simply show up late. Nobody notices that on
    their own.
    """

    entity_description = BinarySensorEntityDescription(
        key="webhook_active",
        translation_key="instance_webhook",
        entity_category=EntityCategory.DIAGNOSTIC,
    )

    def __init__(self, coordinator: NexviewCoordinator, instance_key: str) -> None:
        super().__init__(coordinator, instance_key, "webhook_active")

    @property
    def is_on(self) -> bool:
        return bool(self.instance and self.instance.webhook_active)

    @property
    def available(self) -> bool:
        """Unknown is not off - older Nexview versions do not report this."""
        return (
            super().available
            and self.instance is not None
            and self.instance.webhook_active is not None
        )


class NexviewMyQuotaExhausted(NexviewEntity, BinarySensorEntity):
    """Ob das eigene Konto gerade nichts mehr anfragen kann.

    Dieselbe Regel wie bei fremden Konten: Stückzahl und Speicher gelten
    beide, und eines reicht.
    """

    entity_description = BinarySensorEntityDescription(
        key="my_quota_exhausted",
        translation_key="my_quota_exhausted",
        device_class=BinarySensorDeviceClass.PROBLEM,
    )

    def __init__(self, coordinator: NexviewCoordinator) -> None:
        super().__init__(coordinator, "my_quota_exhausted")

    @property
    def is_on(self) -> bool:
        eigenes = self.coordinator.data.personal
        return bool(eigenes and eigenes.exhausted)
