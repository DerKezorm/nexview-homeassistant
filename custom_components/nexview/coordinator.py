"""One poll, however much it is allowed to see.

⚠️ **What a key may do is read on every cycle, not only at setup.** Somebody
can mark a key read only, or an account can lose its role, while Home Assistant
runs. Reading it once at setup would leave buttons on screen that answer 403
for the rest of the year.

⚠️ **Nothing optional may take the rest down with it.** Every call after the
identity is allowed to fail on its own; the snapshot then simply carries less.
Transmission learned this the hard way in 2026: one health check inside the
coordinator, and its failure pulled every unrelated sensor to unavailable. The
feature was removed again six weeks later.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    CAP_ADMINISTER,
    CAP_DECIDE,
    Instance,
    NexviewAuthError,
    NexviewClient,
    NexviewError,
    Snapshot,
)
from .const import CONF_ACCOUNTS, DOMAIN, POLL_IDLE, POLL_PUSHED

_LOGGER = logging.getLogger(__name__)

type NexviewConfigEntry = ConfigEntry[NexviewCoordinator]

#: What ``_optional`` hands back when the call worked.
_T = TypeVar("_T")


class NexviewCoordinator(DataUpdateCoordinator[Snapshot]):
    """Asks Nexview what it is allowed to ask, on a rhythm that follows the push."""

    config_entry: NexviewConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NexviewConfigEntry,
        client: NexviewClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=POLL_IDLE,
        )
        self.client = client
        self._pushing = False
        #: Set once the main device exists, so instances and accounts can hang
        #: off it. Empty only in the moment between the first fetch and that.
        self.main_device_id: str | None = None
        #: Which optional calls are currently failing. Kept so that a lasting
        #: outage is reported once rather than every thirty seconds - and so
        #: that its recovery is reported too, which is the half that usually
        #: gets forgotten.
        self._failing: set[str] = set()

    @property
    def pushing(self) -> bool:
        """Whether Nexview currently calls us instead of us asking."""
        return self._pushing

    def set_pushing(self, pushing: bool) -> None:
        """Switch the rhythm when the way back comes up or goes away.

        ⚠️ **The slow poll stays.** Turning it off entirely would be cheaper,
        and one integration in the core does exactly that - but a single lost
        call then leaves a wrong number on screen until the next event happens
        to arrive, with nothing to say that anything is wrong.
        """
        if pushing == self._pushing:
            return
        self._pushing = pushing
        self.update_interval = POLL_PUSHED if pushing else POLL_IDLE
        _LOGGER.debug(
            "Nexview push %s, asking every %s",
            "established" if pushing else "lost",
            self.update_interval,
        )

    async def async_wake(self) -> None:
        """Nexview called: fetch now rather than at the next tick."""
        await self.async_request_refresh()

    async def _async_update_data(self) -> Snapshot:
        try:
            identity = await self.client.identity()
        except NexviewAuthError as err:
            # Starts the re-auth flow instead of retrying forever with a key
            # that will never work again.
            raise ConfigEntryAuthFailed(str(err)) from err
        except NexviewError as err:
            raise UpdateFailed(str(err)) from err

        snapshot = Snapshot(identity=identity)

        if identity.may(CAP_ADMINISTER):
            snapshot.tile = await self._optional("dashboard", self.client.tile())

            # ⚠️ **Once, then shared.** The analysis is the single most
            # expensive thing Nexview computes for us, and both the instances
            # and the media servers read from it. Asking twice would double
            # that for nothing.
            analysis = await self._optional("analysis", self.client.analysis())
            if analysis is not None:
                snapshot.instances = {
                    i.key: i
                    for i in (
                        Instance.from_analysis(raw)
                        for raw in analysis.get("instanzen") or ()
                    )
                    if i.key
                }

            servers = await self._optional(
                "media servers", self.client.servers(analysis)
            )
            if servers is not None:
                snapshot.servers = {s.key: s for s in servers if s.key}

            # Only the accounts somebody asked for. Fetching the rest and
            # throwing them away would still mean pulling names out of Nexview
            # for no reason.
            wanted = self.wanted_accounts
            if wanted:
                accounts = await self._optional("accounts", self.client.accounts())
                if accounts is not None:
                    snapshot.accounts = {
                        a.user_id: a for a in accounts if a.user_id in wanted
                    }

        if identity.may(CAP_DECIDE):
            snapshot.pending_count = await self._optional(
                "pending count", self.client.pending_count()
            )
            # Only worth asking when something is actually waiting - the call
            # fetches a list, and an empty queue makes it pointless.
            if snapshot.pending_count:
                snapshot.oldest_pending_hours = await self._optional(
                    "oldest request", self.client.oldest_pending_hours()
                )

        snapshot.version = await self._optional("version", self.client.version())
        return snapshot

    @property
    def wanted_accounts(self) -> set[int]:
        """Which accounts the operator picked in the options."""
        return {int(i) for i in self.config_entry.options.get(CONF_ACCOUNTS, [])}

    async def _optional(self, what: str, awaitable: Awaitable[_T]) -> _T | None:
        """Run a call whose failure must not take the rest of the poll down.

        Returns ``None`` instead of raising. The entities that depend on it go
        unavailable by themselves, and everything else keeps its value.
        """
        try:
            ergebnis = await awaitable
        except NexviewAuthError:
            # Rights shrank between the identity call and this one. Not worth a
            # re-auth flow: the next cycle reads the new capabilities anyway.
            _LOGGER.debug("Nexview no longer allows reading the %s", what)
            self._failing.discard(what)
            return None
        except NexviewError as err:
            # ⚠️ Once, not every thirty seconds. A log that repeats the same
            # line all night buries whatever else went wrong that night.
            if what not in self._failing:
                self._failing.add(what)
                _LOGGER.warning("Nexview stopped answering for the %s: %s", what, err)
            else:
                _LOGGER.debug("Still no %s from Nexview: %s", what, err)
            return None

        if what in self._failing:
            self._failing.discard(what)
            _LOGGER.info("Nexview is answering for the %s again", what)
        return ergebnis
