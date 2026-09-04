"""The way back: Nexview calls us instead of us asking.

**Two steps.** Nexview refuses to deliver to an address that has not proven
itself: it sends a test message carrying a four digit code, and only a caller
who reads that code back gets switched on. That is a good rule - an HTTP 200
from a push service means "accepted", not "arrived" - and it works as well for
a machine as for a person, because the payload carries the code in its own
``code`` field instead of only inside a translated sentence.

⚠️ **This address belongs to one key, and it is nobody else's business.**
Nexview keeps two kinds of notification target apart. A house-wide one is a
shared mailbox an operator sets up, and its messages are announcements: they
name the title and never the person. The one registered here has an owner, and
it carries exactly what that owner also sees in their Nexview notification bell
- "your title is ready", not "a title is ready". Nothing about anybody else
reaches it, which is why a personal key may register one at all.

⚠️ **The webhook only accepts calls from the local network.** Nexview stands
next to Home Assistant, so nothing has to be reachable from the internet - no
port forwarding, no cloud subscription, no address that outlives this entry.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp.web import Request, Response
from homeassistant.components import webhook
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import NexviewError, NexviewNotFoundError
from .const import (
    CONF_WEBHOOK_ID,
    DOMAIN,
    EVENT_OPERATIONS,
    EVENT_ROUTING,
    TARGET_PREFIX,
)
from .coordinator import NexviewConfigEntry

_LOGGER = logging.getLogger(__name__)

#: How long we wait for Nexview's test message after asking for it. It arrives
#: while the request is still open, so this is a guard against nothing
#: arriving at all, not a delay anyone will sit through.
CODE_TIMEOUT = 30


def signal_event(entry_id: str) -> str:
    """Where incoming notifications are announced inside Home Assistant."""
    return f"{DOMAIN}_event_{entry_id}"


class NexviewWebhook:
    """Receives Nexview's calls and, on request, sets itself up over there."""

    def __init__(self, hass: HomeAssistant, entry: NexviewConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        #: Kennt dieses Nexview die Adresse fuer Rueckkanaele ueberhaupt?
        #:
        #: ⚠️ Der Grund wird gemerkt, nicht aus der Version geraten. Eine
        #: Versionsnummer sagt, was eingebaut sein *sollte*; ein 404 sagt, was
        #: wirklich antwortet - und nur der zweite stimmt auch hinter einem
        #: Proxy, der Pfade filtert.
        self.zu_alt = False
        self.webhook_id: str = entry.data[CONF_WEBHOOK_ID]
        self._awaiting_code: asyncio.Future[str] | None = None

    # --- Receiving --------------------------------------------------------

    def register(self) -> None:
        webhook.async_register(
            self.hass,
            DOMAIN,
            f"Nexview {self.entry.title}",
            self.webhook_id,
            self._handle,
            local_only=True,
            allowed_methods=["POST"],
        )

    def unregister(self) -> None:
        webhook.async_unregister(self.hass, self.webhook_id)

    @property
    def url(self) -> str:
        """The address Nexview should call. Internal on purpose."""
        return webhook.async_generate_url(
            self.hass, self.webhook_id, allow_external=False
        )

    async def _handle(
        self, hass: HomeAssistant, webhook_id: str, request: Request
    ) -> Response:
        """One call from Nexview.

        ⚠️ **Never fails loudly.** Nexview keeps an outbox and retries three
        times; an error here would earn a retry for a message we already have.
        Anything unexpected is logged and answered with 200.
        """
        try:
            payload = await request.json()
        except ValueError:
            _LOGGER.warning("Nexview sent something that was not JSON")
            return Response(status=200)

        if not isinstance(payload, dict) or payload.get("source") != "nexview":
            _LOGGER.warning(
                "A call arrived at the Nexview webhook that was not from Nexview"
            )
            return Response(status=200)

        code = payload.get("code")
        if code and self._awaiting_code is not None and not self._awaiting_code.done():
            # The test message. It confirms the connection and is not news.
            self._awaiting_code.set_result(str(code))
            return Response(status=200)

        self._announce(payload)
        coordinator = self.entry.runtime_data
        coordinator.set_pushing(True)
        await coordinator.async_wake()
        return Response(status=200)

    def _announce(self, payload: dict[str, Any]) -> None:
        """Sort one notification onto the right event entity.

        ⚠️ **Unknown types are not dropped.** Nexview will grow new ones, and
        an integration that silently swallows them looks broken to whoever is
        waiting for an automation to fire. What we do not know lands on the
        operations entity as ``other``, carrying its original name.
        """
        kind = str(payload.get("event") or "")
        group, event_type = EVENT_ROUTING.get(kind, (EVENT_OPERATIONS, "other"))
        async_dispatcher_send(
            self.hass,
            signal_event(self.entry.entry_id),
            group,
            event_type,
            {
                "nexview_event": kind,
                "title": payload.get("title"),
                "body": payload.get("body"),
                "level": payload.get("level"),
                "url": payload.get("url"),
                "image": payload.get("image"),
            },
        )

    # --- Setting ourselves up over there ----------------------------------

    def _sprache(self) -> str:
        """In welcher Sprache Nexview seine Meldungen schicken soll.

        ⚠️ **Nach der Sprache dieses Home Assistant, nicht fest Englisch.**
        Die Meldungen kommen als fertige Saetze und landen in
        Benachrichtigungen, die ein Mensch liest. Nexview kennt genau zwei
        Sprachen; alles, was nicht Deutsch ist, bekommt Englisch.
        """
        eingestellt = (self.hass.config.language or "en").lower()
        return "de" if eingestellt.startswith("de") else "en"

    async def async_ensure_target(self) -> bool:
        """Make sure Nexview knows this address. Returns whether it does.

        Never re-registers an address that already works. Rewriting a working
        configuration on every restart is how an integration quietly undoes
        what somebody set by hand - and here it would also mean a fresh
        confirmation code on every reboot.
        """
        client = self.entry.runtime_data.client
        url = self.url
        name = f"{TARGET_PREFIX} ({self.hass.config.location_name})"

        self.zu_alt = False
        try:
            stand = await client.push_state()
        except NexviewNotFoundError:
            self.zu_alt = True
            # An older Nexview. Nothing to fall back to: before 0.30 only an
            # operator could register a target at all, and it would then have
            # received every notification in the house instead of this
            # person's. The repair issue says so in as many words.
            _LOGGER.info(
                "This Nexview does not offer a callback address yet (needs 0.30)"
            )
            return False
        except NexviewError as err:
            _LOGGER.debug("Could not ask Nexview about the way back: %s", err)
            return False

        if stand.get("bestaetigt") and stand.get("url") == url:
            return True

        try:
            return await self._enrol(name, url)
        except NexviewError as err:
            _LOGGER.info("Nexview could not be told about this address: %s", err)
            return False

    async def async_forget_target(self) -> None:
        """Nexview soll uns nicht mehr anrufen.

        ⚠️ **Ohne das bliebe ein abgeschalteter Haken folgenlos.** Nexview
        funkte weiter an eine Adresse, die niemand mehr hoeren will, und der
        Postausgang sammelte Fehlversuche, sobald dieses Home Assistant einmal
        nicht laeuft. Ein Fehler beim Aufraeumen wird nur notiert: Wer den
        Haken ausmacht, soll nicht an einem unerreichbaren Nexview haengen
        bleiben.
        """
        try:
            await self.entry.runtime_data.client.push_remove()
        except NexviewError as err:
            _LOGGER.debug("Could not withdraw the callback address: %s", err)

    async def _enrol(self, name: str, url: str) -> bool:
        """Register, catch the code from the test message, confirm."""
        client = self.entry.runtime_data.client
        self._awaiting_code = self.hass.loop.create_future()
        try:
            await client.push_register(name, url, self._sprache())
            try:
                code = await asyncio.wait_for(self._awaiting_code, CODE_TIMEOUT)
            except TimeoutError:
                # Nexview says it sent the message and it never arrived. Almost
                # always the address: Nexview cannot reach this Home Assistant.
                _LOGGER.info(
                    "Nexview sent its test message to %s and it never arrived", url
                )
                return False
        finally:
            self._awaiting_code = None

        await client.push_confirm(code)
        _LOGGER.debug("Nexview now calls %s", url)
        return True
