"""Setup, and what a key is allowed to bring with it.

⚠️ **Entities are found by their unique id here, not by their entity id.**
An entity id is built from translated names and could change without anything
being wrong. The unique id is ours and is the thing that must never move.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.nexview.const import (
    ATTR_REQUEST_ID,
    DOMAIN,
    SERVICE_APPROVE,
    SERVICE_REJECT,
)

from .conftest import (
    IDENTITY_READONLY,
    IDENTITY_USER,
    TILE,
    URL,
    setup_entry,
)


def _keys(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    """Which sensors and switches this entry actually created."""
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"
    return {
        entity.unique_id.removeprefix(prefix)
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
    }


@pytest.fixture(autouse=True)
def no_webhook_enrolment():
    """The way back has its own test file. Here it only has to not get in the way."""
    with patch(
        "custom_components.nexview.webhook.NexviewWebhook.async_ensure_target",
        AsyncMock(return_value=True),
    ):
        yield


class TestWhatTheKeyBringsWithIt:
    async def test_an_operator_key_gets_everything(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        await setup_entry(hass, entry)

        assert entry.state is ConfigEntryState.LOADED
        keys = _keys(hass, entry)
        assert "pending_requests" in keys
        assert "free_space" in keys
        assert "findings_error" in keys
        assert "reachable" in keys
        assert "event_requests" in keys

    async def test_a_read_only_key_keeps_the_figures_and_loses_the_rest(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        """⚠️ The case the whole capability list exists for.

        The account is an administrator, so the house figures stay. The key
        may not write, so nothing that decides anything is created - not even
        the waiting-requests sensor, which needs the right to decide to be
        readable at all.
        """
        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_READONLY)
        aioclient_mock.get(f"{URL}/api/v1/dashboard", json=TILE)
        aioclient_mock.get(f"{URL}/api/settings/channels/webhook/targets", json=[])

        await setup_entry(hass, entry)

        keys = _keys(hass, entry)
        assert "free_space" in keys, "An administrator may still read the house."
        assert "pending_requests" not in keys, (
            "Deciding is out, so the waiting count has no business being here."
        )

    async def test_an_ordinary_key_creates_almost_nothing(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        """⚠️ Not a dozen permanently unavailable entities.

        Creating everything and leaving most of it grey is what makes a
        working integration look broken to anybody whose account is not an
        administrator.
        """
        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_USER)
        aioclient_mock.get(f"{URL}/api/settings/channels/webhook/targets", json=[])

        await setup_entry(hass, entry)

        keys = _keys(hass, entry)
        assert keys & {"free_space", "findings_error", "pending_requests"} == set()
        assert "reachable" in keys, "Whether Nexview answers is everybody's business."

    async def test_the_figures_arrive(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_pending_requests"
        )
        assert hass.states.get(entity_id).state == "4"


class TestDeciding:
    async def test_approving_reaches_nexview(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        await setup_entry(hass, entry)

        with patch(
            "custom_components.nexview.api.NexviewClient.approve", AsyncMock()
        ) as approve:
            await hass.services.async_call(
                DOMAIN, SERVICE_APPROVE, {ATTR_REQUEST_ID: 42}, blocking=True
            )

        approve.assert_awaited_once_with(42)

    async def test_a_reason_is_passed_on(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        await setup_entry(hass, entry)

        with patch(
            "custom_components.nexview.api.NexviewClient.reject", AsyncMock()
        ) as reject:
            await hass.services.async_call(
                DOMAIN,
                SERVICE_REJECT,
                {ATTR_REQUEST_ID: 42, "reason": "Already there"},
                blocking=True,
            )

        reject.assert_awaited_once_with(42, "Already there")

    async def test_a_read_only_key_is_told_why_not(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        """⚠️ Refused here, with a sentence, instead of over there with a 403.

        The action exists because another entry might be able to use it. What
        it must not do is send a call that cannot possibly work and then show
        somebody a bare HTTP code in an automation trace.
        """
        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_READONLY)
        aioclient_mock.get(f"{URL}/api/v1/dashboard", json=TILE)
        aioclient_mock.get(f"{URL}/api/settings/channels/webhook/targets", json=[])

        await setup_entry(hass, entry)

        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN, SERVICE_APPROVE, {ATTR_REQUEST_ID: 42}, blocking=True
            )

    async def test_an_unknown_request_number_is_named_as_such(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Found by running this against a real Nexview.

        Nexview answers 404 both for an address it does not have and for a
        request number that was already decided. Passed through unchanged, the
        second case reads as "Nexview has nothing at
        /api/admin/requests/42/approve" - which sends somebody looking for a
        broken integration instead of a stale number in their automation.
        """
        from custom_components.nexview.api import NexviewNotFoundError

        await setup_entry(hass, entry)

        with (
            patch(
                "custom_components.nexview.api.NexviewClient.approve",
                AsyncMock(
                    side_effect=NexviewNotFoundError("/api/admin/requests/42/approve")
                ),
            ),
            pytest.raises(ServiceValidationError) as fehler,
        ):
            await hass.services.async_call(
                DOMAIN, SERVICE_APPROVE, {ATTR_REQUEST_ID: 42}, blocking=True
            )

        assert fehler.value.translation_key == "unknown_request"

    async def test_the_actions_exist_even_with_nothing_connected(
        self, hass: HomeAssistant
    ) -> None:
        """⚠️ Registered at startup, not per entry.

        Actions that only exist while an entry is loaded make Home Assistant
        unable to check automations that use them, and an automation pointing
        at a missing action reads as broken.
        """
        from custom_components.nexview import async_setup

        await async_setup(hass, {})
        assert hass.services.has_service(DOMAIN, SERVICE_APPROVE)


class TestWhenTheKeyStopsWorking:
    async def test_a_revoked_key_asks_for_a_new_one(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        aioclient_mock.get(f"{URL}/api/v1/me", status=401)

        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.SETUP_ERROR
        assert any(
            flow["context"]["source"] == "reauth"
            for flow in hass.config_entries.flow.async_progress()
        )
