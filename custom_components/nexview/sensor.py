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
from homeassistant.const import EntityCategory, UnitOfInformation, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import (
    CAP_ADMINISTER,
    CAP_DECIDE,
    CAP_READ,
    AccountUsage,
    Instance,
    MediaServer,
    Snapshot,
)
from .coordinator import NexviewConfigEntry, NexviewCoordinator
from .entity import (
    NexviewAccountEntity,
    NexviewEntity,
    NexviewInstanceEntity,
    NexviewServerEntity,
)

#: ⚠️ **No limit needed.** Every entity here reads from one shared poll, so
#: there is nothing to serialise - Home Assistant asks for this to be stated
#: rather than assumed.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NexviewSensorDescription(SensorEntityDescription):
    """A sensor plus the two things that decide whether it exists at all."""

    #: What the key must be allowed to do for this sensor to make sense.
    requires: str
    #: ``None`` means "no figure right now" - the entity goes unavailable
    #: rather than showing a zero that nobody measured. Float rather than int
    #: because one of these is a duration in hours.
    value_fn: Callable[[Snapshot], float | None]


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
        key="oldest_pending",
        translation_key="oldest_pending",
        requires=CAP_DECIDE,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        # ⚠️ ``None`` when nothing waits, and that is the point: a zero would
        # read as "somebody just asked", which is the opposite of an empty
        # queue. The entity goes unavailable instead.
        value_fn=lambda s: s.oldest_pending_hours,
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


#: Das eigene Konto. Diese Werte hängen an keiner Rolle - jeder Schlüssel
#: darf sie lesen - und sie stehen alle auf zugesagten Adressen.
PERSONAL_SENSORS: tuple[NexviewSensorDescription, ...] = (
    NexviewSensorDescription(
        key="my_movie_quota_used",
        translation_key="my_movie_quota_used",
        requires=CAP_READ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.personal.movies.used if s.personal else None,
    ),
    NexviewSensorDescription(
        key="my_movie_quota_remaining",
        translation_key="my_movie_quota_remaining",
        requires=CAP_READ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.personal.movies.remaining if s.personal else None,
    ),
    NexviewSensorDescription(
        key="my_series_quota_used",
        translation_key="my_series_quota_used",
        requires=CAP_READ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.personal.series.used if s.personal else None,
    ),
    NexviewSensorDescription(
        key="my_series_quota_remaining",
        translation_key="my_series_quota_remaining",
        requires=CAP_READ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.personal.series.remaining if s.personal else None,
    ),
    NexviewSensorDescription(
        key="my_storage_used",
        translation_key="my_storage_used",
        requires=CAP_READ,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.personal.storage.used if s.personal else None,
    ),
    NexviewSensorDescription(
        key="my_storage_remaining",
        translation_key="my_storage_remaining",
        requires=CAP_READ,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.personal.storage.remaining if s.personal else None,
    ),
    NexviewSensorDescription(
        key="my_items",
        translation_key="my_items",
        requires=CAP_READ,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.personal.items if s.personal else None,
    ),
    NexviewSensorDescription(
        key="my_unread",
        translation_key="my_unread",
        requires=CAP_READ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.personal.unread if s.personal else None,
    ),
    NexviewSensorDescription(
        key="my_open_tickets",
        translation_key="my_open_tickets",
        requires=CAP_READ,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.personal.open_tickets if s.personal else None,
    ),
)


@dataclass(frozen=True, kw_only=True)
class NexviewAccountSensorDescription(SensorEntityDescription):
    """One figure about one account."""

    value_fn: Callable[[AccountUsage], int | None]
    #: Whether this figure exists at all for a given account.
    #:
    #: ⚠️ **Unbegrenzt heisst nicht "unbekannt".** Wo Nexview kein Limit
    #: setzt, gibt es keine Restmenge - und ein Eintrag, der dauerhaft "Nicht
    #: verfuegbar" zeigt, liest sich wie ein Fehler statt wie eine Freiheit.
    #: Solche Eintraege entstehen deshalb gar nicht erst, und sie entstehen
    #: von selbst, sobald jemand in Nexview doch eine Grenze setzt.
    applies_to: Callable[[AccountUsage], bool] = lambda a: True


ACCOUNT_SENSORS: tuple[NexviewAccountSensorDescription, ...] = (
    NexviewAccountSensorDescription(
        key="movie_quota_used",
        translation_key="movie_quota_used",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda a: a.movies.used,
    ),
    NexviewAccountSensorDescription(
        key="movie_quota_remaining",
        translation_key="movie_quota_remaining",
        applies_to=lambda a: not a.movies.unlimited,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda a: a.movies.remaining,
    ),
    NexviewAccountSensorDescription(
        key="series_quota_used",
        translation_key="series_quota_used",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda a: a.series.used,
    ),
    NexviewAccountSensorDescription(
        key="series_quota_remaining",
        translation_key="series_quota_remaining",
        applies_to=lambda a: not a.series.unlimited,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda a: a.series.remaining,
    ),
    NexviewAccountSensorDescription(
        key="open_requests",
        translation_key="account_open_requests",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda a: a.pending,
    ),
    NexviewAccountSensorDescription(
        key="storage_used",
        translation_key="storage_used",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda a: a.storage.used,
    ),
    NexviewAccountSensorDescription(
        key="storage_remaining",
        translation_key="storage_remaining",
        applies_to=lambda a: not a.storage.unlimited,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda a: a.storage.remaining,
    ),
)


@dataclass(frozen=True, kw_only=True)
class NexviewInstanceSensorDescription(SensorEntityDescription):
    """One figure about one Radarr or Sonarr."""

    value_fn: Callable[[Instance], int | None]


INSTANCE_SENSORS: tuple[NexviewInstanceSensorDescription, ...] = (
    NexviewInstanceSensorDescription(
        key="queue",
        translation_key="instance_queue",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda i: i.queue,
    ),
    NexviewInstanceSensorDescription(
        key="queue_stuck",
        translation_key="instance_queue_stuck",
        state_class=SensorStateClass.MEASUREMENT,
        # ⚠️ The interesting half. A long queue is a busy evening; a stuck one
        # is something nobody will notice until somebody complains.
        value_fn=lambda i: i.queue_stuck,
    ),
    NexviewInstanceSensorDescription(
        key="gaps",
        translation_key="instance_gaps",
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda i: i.gaps,
    ),
)


@dataclass(frozen=True, kw_only=True)
class NexviewServerSensorDescription(SensorEntityDescription):
    """One figure about one media server."""

    value_fn: Callable[[MediaServer], int | None]


SERVER_SENSORS: tuple[NexviewServerSensorDescription, ...] = (
    NexviewServerSensorDescription(
        key="playing",
        translation_key="server_playing",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.playing,
    ),
    NexviewServerSensorDescription(
        key="transcoding",
        translation_key="server_transcoding",
        state_class=SensorStateClass.MEASUREMENT,
        # What a slow evening looks like from the outside: the server is
        # converting rather than sending the file as it lies.
        value_fn=lambda s: s.transcoding,
    ),
    NexviewServerSensorDescription(
        key="titles",
        translation_key="server_titles",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.titles,
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

    # ⚠️ **Die eigenen Zahlen, für jeden Schlüssel.** Ohne sie bekommt ein
    # persönlicher Zugang nichts als "Nexview antwortet" - und genau so sah es
    # in der Praxis auch aus. Die Rest-Einträge folgen derselben Regel wie bei
    # fremden Konten: kein Eintrag, wo es keine Grenze gibt.
    eigenes = coordinator.data.personal
    if eigenes is not None:
        ohne_grenze = {
            "my_movie_quota_remaining": eigenes.movies.unlimited,
            "my_series_quota_remaining": eigenes.series.unlimited,
            "my_storage_remaining": eigenes.storage.unlimited,
        }
        async_add_entities(
            NexviewSensor(coordinator, description)
            for description in PERSONAL_SENSORS
            if not ohne_grenze.get(description.key, False)
        )

    # ⚠️ **Instances and accounts come and go while this runs.** Somebody adds
    # a second Sonarr, or picks another account in the options. Building the
    # list once at setup would mean a restart for every change.
    known_instances: set[str] = set()
    known_accounts: set[int] = set()
    known_servers: set[str] = set()
    #: Welche Konto-Werte schon existieren, als (Konto, Schluessel).
    angelegt: set[tuple[int, str]] = set()

    @callback
    def _add_new() -> None:
        neu: list[SensorEntity] = []

        current_instances = set(coordinator.data.instances)
        # ⚠️ The intersection first: an instance that vanished and came back
        # must get its entities created again, not be remembered as known.
        known_instances.intersection_update(current_instances)
        for key in current_instances - known_instances:
            neu.append(NexviewInstanceProblems(coordinator, key))
            neu.append(NexviewInstanceVersion(coordinator, key))
            neu.extend(
                NexviewInstanceSensor(coordinator, key, d) for d in INSTANCE_SENSORS
            )
        known_instances.update(current_instances)

        current_servers = set(coordinator.data.servers)
        known_servers.intersection_update(current_servers)
        for key in current_servers - known_servers:
            neu.extend(
                NexviewServerSensor(coordinator, key, d) for d in SERVER_SENSORS
            )
        known_servers.update(current_servers)

        # Nicht nur das Konto, auch welche seiner Werte schon angelegt sind:
        # Setzt jemand in Nexview nachtraeglich eine Grenze, entsteht der
        # zugehoerige Eintrag beim naechsten Abruf.
        for user_id, konto in coordinator.data.accounts.items():
            if user_id not in known_accounts:
                continue
            neu.extend(
                NexviewAccountSensor(coordinator, user_id, d)
                for d in ACCOUNT_SENSORS
                if d.applies_to(konto)
                and (user_id, d.key) not in angelegt
            )

        current_accounts = set(coordinator.data.accounts)
        known_accounts.intersection_update(current_accounts)
        for user_id in current_accounts - known_accounts:
            konto = coordinator.data.accounts[user_id]
            neu.extend(
                NexviewAccountSensor(coordinator, user_id, d)
                for d in ACCOUNT_SENSORS
                if d.applies_to(konto)
            )
        known_accounts.update(current_accounts)

        for e in neu:
            if isinstance(e, NexviewAccountSensor):
                angelegt.add((e.user_id, e.entity_description.key))
        if neu:
            async_add_entities(neu)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class NexviewSensor(NexviewEntity, SensorEntity):
    entity_description: NexviewSensorDescription

    def __init__(
        self, coordinator: NexviewCoordinator, description: NexviewSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Unavailable when there is no figure, not zero.

        A key can lose a right while Home Assistant runs, and Nexview can
        answer one call and not the next. Showing a zero in either case would
        be a measurement nobody took.
        """
        return super().available and self.native_value is not None


class NexviewInstanceProblems(NexviewInstanceEntity, SensorEntity):
    """How much this Radarr or Sonarr is complaining about itself."""

    entity_description = SensorEntityDescription(
        key="problems",
        translation_key="instance_problems",
        state_class=SensorStateClass.MEASUREMENT,
    )

    def __init__(self, coordinator: NexviewCoordinator, instance_key: str) -> None:
        super().__init__(coordinator, instance_key, "problems")

    @property
    def native_value(self) -> int | None:
        return self.instance.problems if self.instance else None


class NexviewInstanceVersion(NexviewInstanceEntity, SensorEntity):
    """Which version the instance runs. Diagnostic, and off by default."""

    entity_description = SensorEntityDescription(
        key="version",
        translation_key="instance_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    )

    def __init__(self, coordinator: NexviewCoordinator, instance_key: str) -> None:
        super().__init__(coordinator, instance_key, "version")

    @property
    def native_value(self) -> str | None:
        return self.instance.version if self.instance else None


class NexviewAccountSensor(NexviewAccountEntity, SensorEntity):
    """One figure about one account."""

    entity_description: NexviewAccountSensorDescription

    def __init__(
        self,
        coordinator: NexviewCoordinator,
        user_id: int,
        description: NexviewAccountSensorDescription,
    ) -> None:
        super().__init__(coordinator, user_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | None:
        return self.entity_description.value_fn(self.account) if self.account else None

    @property
    def available(self) -> bool:
        """⚠️ No allowance is not the same as an allowance of zero.

        Where Nexview grants unlimited, ``remaining`` has no number, and the
        entity says so instead of showing a nought that would look like an
        account with nothing left.
        """
        return super().available and self.native_value is not None


class NexviewInstanceSensor(NexviewInstanceEntity, SensorEntity):
    """One figure about one Radarr or Sonarr."""

    entity_description: NexviewInstanceSensorDescription

    def __init__(
        self,
        coordinator: NexviewCoordinator,
        instance_key: str,
        description: NexviewInstanceSensorDescription,
    ) -> None:
        super().__init__(coordinator, instance_key, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | None:
        return self.entity_description.value_fn(self.instance) if self.instance else None

    @property
    def available(self) -> bool:
        """Not measured is not the same as zero."""
        return super().available and self.native_value is not None


class NexviewServerSensor(NexviewServerEntity, SensorEntity):
    """One figure about one media server."""

    entity_description: NexviewServerSensorDescription

    def __init__(
        self,
        coordinator: NexviewCoordinator,
        server_key: str,
        description: NexviewServerSensorDescription,
    ) -> None:
        super().__init__(coordinator, server_key, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | None:
        return self.entity_description.value_fn(self.server) if self.server else None

    @property
    def available(self) -> bool:
        """⚠️ The library count may be missing while the streams are not.

        Nexview only knows how many titles a server holds once its comparison
        has run. Until then that one sensor has nothing to say, and the two
        about playback still do.
        """
        return super().available and self.native_value is not None
