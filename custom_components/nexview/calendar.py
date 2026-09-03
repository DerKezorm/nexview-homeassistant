"""What is coming out, next to everything else in the house.

Nexview already keeps a calendar of cinema dates and episode dates. As a Home
Assistant calendar it sits beside the bin collection and the school holidays,
and an automation can ask "is a new episode out tonight" without knowing
anything about media at all.

⚠️ **All-day entries, deliberately.** Nexview knows a release date, not a
release time. Inventing 8pm would put a wrong time on every card in the house.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import NexviewError, Release
from .coordinator import NexviewConfigEntry, NexviewCoordinator
from .entity import NexviewEntity

_LOGGER = logging.getLogger(__name__)

#: How long the list of upcoming titles is kept before asking again. The
#: calendar changes by the day, not by the minute, and Nexview builds it from
#: TMDB - there is no reason to ask on every poll.
FRESH_FOR = timedelta(minutes=30)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NexviewConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([NexviewCalendar(entry.runtime_data)])


class NexviewCalendar(NexviewEntity, CalendarEntity):
    """Upcoming releases, as a calendar."""

    _attr_translation_key = "upcoming"

    def __init__(self, coordinator: NexviewCoordinator) -> None:
        super().__init__(coordinator, "calendar")
        self._releases: list[Release] = []
        self._fetched: datetime | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._refresh()

    async def async_update(self) -> None:
        await self._refresh()

    async def _refresh(self) -> None:
        now = dt_util.utcnow()
        if self._fetched is not None and now - self._fetched < FRESH_FOR:
            return
        try:
            self._releases = await self.coordinator.client.releases()
            self._fetched = now
        except NexviewError as err:
            # ⚠️ Keep whatever was fetched last. A calendar that empties
            # itself because one call failed looks like everything got
            # cancelled.
            _LOGGER.debug("Could not read the Nexview calendar: %s", err)

    @property
    def event(self) -> CalendarEvent | None:
        """The next one, which is what a dashboard card shows."""
        today = dt_util.now().date()
        upcoming = sorted(
            (e for e in self._as_events() if e.end > today), key=lambda e: e.start
        )
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        await self._refresh()
        von, bis = start_date.date(), end_date.date()
        return [e for e in self._as_events() if e.start < bis and e.end > von]

    def _as_events(self) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for release in self._releases:
            try:
                tag = date.fromisoformat(release.date)
            except ValueError:
                continue
            events.append(
                CalendarEvent(
                    # An all-day event in Home Assistant ends on the following
                    # day; ending on the same one would make it zero long.
                    start=tag,
                    end=tag + timedelta(days=1),
                    summary=(
                        f"{release.title} - {release.episode}"
                        if release.episode
                        else release.title
                    ),
                    description=release.summary,
                    uid=release.key or None,
                )
            )
        return events
