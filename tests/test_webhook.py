"""The way back, which is the piece with the most moving parts.

Two things are checked here. That an incoming call becomes the right event -
including one Nexview has not invented yet. And that the integration can set
itself up over in Nexview without anybody copying a four digit code between two
browser tabs, which is the whole reason the payload carries that code in a
field of its own.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.nexview.const import DOMAIN, POLL_IDLE, POLL_PUSHED

from .conftest import URL, WEBHOOK_ID, setup_entry


def _payload(event: str, **extra: Any) -> dict[str, Any]:
    return {
        "source": "nexview",
        "event": event,
        "level": "high",
        "title": "Dune",
        "body": "waiting for a decision",
        "image": None,
        "url": f"{URL}/admin/requests",
        "code": None,
        **extra,
    }


async def _call_webhook(hass_client_no_auth, payload: dict[str, Any]):
    client = await hass_client_no_auth()
    return await client.post(f"/api/webhook/{WEBHOOK_ID}", json=payload)


class TestIncomingCalls:
    """Only the receiving half. Setting itself up is the next class down."""

    @pytest.fixture(autouse=True)
    def already_enrolled(self):
        with patch(
            "custom_components.nexview.webhook.NexviewWebhook.async_ensure_target",
            AsyncMock(return_value=True),
        ):
            yield

    async def test_a_waiting_request_becomes_an_event(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        hass_client_no_auth,
    ) -> None:
        await setup_entry(hass, entry)

        await _call_webhook(hass_client_no_auth, _payload("request_pending"))
        await hass.async_block_till_done()

        state = hass.states.get("event.nexview_admin_requests")
        assert state is not None
        assert state.attributes["event_type"] == "pending"
        assert state.attributes["title"] == "Dune"

    async def test_storage_and_requests_stay_apart(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        hass_client_no_auth,
    ) -> None:
        """⚠️ The reason there are three entities and not one.

        Somebody automating on requests must not be woken by a storage
        message. With a single event entity every automation would have to
        check first whether the event was even its own.
        """
        await setup_entry(hass, entry)

        await _call_webhook(hass_client_no_auth, _payload("storage_released"))
        await hass.async_block_till_done()

        storage = hass.states.get("event.nexview_admin_storage")
        requests = hass.states.get("event.nexview_admin_requests")
        assert storage.attributes["event_type"] == "released"
        assert requests.state == "unknown", "The requests entity must not have fired."

    async def test_an_unknown_notification_is_not_dropped(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        hass_client_no_auth,
    ) -> None:
        """⚠️ Nexview will grow notification types this version never saw.

        Swallowing them silently makes the integration look broken to whoever
        waits for an automation that never fires. They land on the operations
        entity, carrying their original name.
        """
        await setup_entry(hass, entry)

        await _call_webhook(hass_client_no_auth, _payload("something_new_entirely"))
        await hass.async_block_till_done()

        state = hass.states.get("event.nexview_admin_operations")
        assert state.attributes["event_type"] == "other"
        assert state.attributes["nexview_event"] == "something_new_entirely"

    async def test_a_call_from_somewhere_else_fires_nothing(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        hass_client_no_auth,
    ) -> None:
        """The address is not a secret worth relying on by itself."""
        await setup_entry(hass, entry)

        response = await _call_webhook(
            hass_client_no_auth, {"source": "somebody_else", "event": "request_pending"}
        )
        await hass.async_block_till_done()

        assert response.status == 200, "Never answer an error - it only earns a retry."
        assert hass.states.get("event.nexview_admin_requests").state == "unknown"


class TestSettingItselfUp:
    async def test_it_catches_its_own_confirmation_code(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        hass_client_no_auth,
    ) -> None:
        """⚠️ The point of the whole exercise.

        Nexview refuses to save a target that has not proven itself: it sends
        a test message with a four digit code, and only a caller who reads it
        back may save. Good rule - an HTTP 200 from a push service means
        "accepted", not "arrived" - and it works for a machine too, as long as
        the machine can find the code. It can, because the payload carries it
        in its own field instead of only inside a translated sentence.
        """
        confirmed: list[str] = []

        async def send_test_message(name: str, url: str) -> None:
            # Nexview calls us while its own request is still open.
            await _call_webhook(hass_client_no_auth, _payload("test", code="4711"))

        nexview.post(
            f"{URL}/api/settings/channels/webhook/targets",
            json={"id": 12, "verified": True},
        )
        nexview.put(
            f"{URL}/api/settings/channels/webhook/targets/12/events", json={}
        )

        with (
            patch(
                "custom_components.nexview.api.NexviewClient.webhook_test",
                AsyncMock(side_effect=send_test_message),
            ),
            patch(
                "custom_components.nexview.api.NexviewClient.webhook_confirm",
                AsyncMock(side_effect=lambda code: confirmed.append(code)),
            ),
        ):
            await setup_entry(hass, entry)

        assert confirmed == ["4711"], "The code from the payload had to come back."
        # Asked of the coordinator, not of the diagnostic sensor: that one is
        # deliberately switched off until somebody turns it on.
        assert entry.runtime_data.pushing is True
        assert entry.runtime_data.update_interval == POLL_PUSHED, (
            "With the way back in place, asking every 30 seconds is waste."
        )

    async def test_the_test_message_does_not_become_news(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        hass_client_no_auth,
    ) -> None:
        """A confirmation is a handshake, not something that happened."""

        async def send_test_message(name: str, url: str) -> None:
            await _call_webhook(hass_client_no_auth, _payload("test", code="1234"))

        nexview.post(
            f"{URL}/api/settings/channels/webhook/targets",
            json={"id": 12, "verified": True},
        )
        nexview.put(f"{URL}/api/settings/channels/webhook/targets/12/events", json={})

        with (
            patch(
                "custom_components.nexview.api.NexviewClient.webhook_test",
                AsyncMock(side_effect=send_test_message),
            ),
            patch(
                "custom_components.nexview.api.NexviewClient.webhook_confirm",
                AsyncMock(),
            ),
        ):
            await setup_entry(hass, entry)

        assert hass.states.get("event.nexview_admin_operations").state == "unknown"

    async def test_an_existing_target_is_left_alone(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        """⚠️ Never rewrite what is already there and working.

        An integration that re-registers itself on every restart quietly undoes
        whatever a person adjusted by hand over there.
        """
        from .conftest import IDENTITY_ADMIN, TILE

        known_url = f"http://ha.test:8123/api/webhook/{WEBHOOK_ID}"

        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_ADMIN)
        aioclient_mock.get(f"{URL}/api/v1/dashboard", json=TILE)
        aioclient_mock.get(
            f"{URL}/api/v1/admin/requests/pending/count", json={"pending": 4}
        )
        aioclient_mock.get(
            f"{URL}/api/settings/channels/webhook/targets",
            json=[{"id": 3, "url": known_url, "verified": True}],
        )

        with (
            patch(
                "custom_components.nexview.webhook.NexviewWebhook.url",
                new_callable=PropertyMock,
                return_value=known_url,
            ),
            patch(
                "custom_components.nexview.api.NexviewClient.webhook_test", AsyncMock()
            ) as sent,
        ):
            await setup_entry(hass, entry)

        assert sent.call_count == 0, "It sent a test message for a target it already had."


class TestWhenNexviewCannotReachUs:
    async def test_it_says_so_instead_of_going_quiet(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ The gap the Seerr integration leaves open.

        Everything keeps working without the push - Home Assistant just asks
        more often - but events arrive late or never, and nothing on screen
        explains why. Seerr's own quality file claims there is no case for a
        repair issue here. There is, and this is it.
        """
        with patch(
            "custom_components.nexview.webhook.CODE_TIMEOUT", 0.05
        ), patch(
            "custom_components.nexview.api.NexviewClient.webhook_test",
            AsyncMock(),  # says it sent something; nothing ever arrives
        ):
            await setup_entry(hass, entry)

        issues = ir.async_get(hass)
        assert issues.async_get_issue(DOMAIN, f"push_missing_{entry.entry_id}")
        assert entry.runtime_data.pushing is False
        assert entry.runtime_data.update_interval == POLL_IDLE, (
            "Without the way back it has to ask often enough to stay useful."
        )
