"""The way back: Nexview calls us instead of us asking.

Nexview already ships a generic webhook channel, and its own source names Home
Assistant as the first case it was built for. Nothing had to be invented here;
the work is in setting it up without making anyone copy a code between two
browser tabs.

**How the four steps fit together.** Nexview refuses to save a target that has
not proven itself: it sends a test message carrying a four digit code, and only
a caller who can read that code back may save. That is a good rule - an HTTP
200 from a push service means "accepted", not "arrived" - and it works just as
well for a machine as for a person, as long as the machine can find the code.
It can: the payload carries it in its own ``code`` field.

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

from .api import NexviewError
from .const import (
    CONF_WEBHOOK_ID,
    DOMAIN,
    EVENT_OPERATIONS,
    EVENT_ROUTING,
    TARGET_PREFIX,
    WEBHOOK_EVENTS,
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

    async def async_ensure_target(self) -> bool:
        """Make sure Nexview knows this address. Returns whether it does.

        Never touches a target that already points at us, and never touches
        anybody else's. Rewriting a working configuration on every restart is
        how an integration quietly undoes what a person set by hand.
        """
        client = self.entry.runtime_data.client
        url = self.url
        name = f"{TARGET_PREFIX} ({self.hass.config.location_name})"

        try:
            existing = await client.webhook_targets()
        except NexviewError as err:
            _LOGGER.debug("Could not read Nexview's notification targets: %s", err)
            return False

        for target in existing:
            if target.get("url") == url:
                if target.get("verified"):
                    return True
                # Ours, but never proven - Nexview will not deliver to it.
                # Setting it up again is the only way out.
                break

        try:
            return await self._enrol(name, url)
        except NexviewError as err:
            _LOGGER.info("Nexview could not be told about this address: %s", err)
            return False

    async def _enrol(self, name: str, url: str) -> bool:
        """Test message, catch the code, confirm, save, subscribe."""
        self._awaiting_code = self.hass.loop.create_future()
        try:
            await self.entry.runtime_data.client.webhook_test(name, url)
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

        client = self.entry.runtime_data.client
        await client.webhook_confirm(code)
        target = await client.webhook_save(name, url)

        target_id = target.get("id")
        if target_id is not None:
            await client.webhook_events(int(target_id), WEBHOOK_EVENTS)

        _LOGGER.debug("Nexview now calls %s", url)
        return True
