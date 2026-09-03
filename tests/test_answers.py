"""The parts that answer rather than count: calendar, update, buttons, actions.

⚠️ **Why the actions matter more than they look.** They are where lists live.
Home Assistant is retiring long lists in entity attributes, and everything this
integration knows that does not fit in a single number is reachable here
instead - which means these have to actually return something usable, not just
not throw.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.nexview.const import (
    DOMAIN,
    SERVICE_ACTIVE_DOWNLOADS,
    SERVICE_GET_QUOTA,
    SERVICE_LIST_REQUESTS,
    SERVICE_SEARCH,
)

from .conftest import ABOUT, IDENTITY_READONLY, TILE, URL, setup_entry

#: What Nexview answers for the request list. Invented titles and invented
#: people - this repository is public.
REQUESTS = [
    {
        "id": 41,
        "title": "Some Film",
        "media_type": "movie",
        "status": "pending_approval",
        "tmdb_id": 1,
        "display_name": "Gast",
        "requested_at": "2026-09-01T10:00:00",
        "laedt_fortschritt": None,
        "avatar_url": "/api/users/avatar/whatever.jpg",
        "for_child_name": "Kind",
    },
    {
        "id": 42,
        "title": "Some Series",
        "media_type": "tv",
        "status": "downloading",
        "tmdb_id": 2,
        "display_name": "Gast",
        "requested_at": "2026-09-02T10:00:00",
        "laedt_fortschritt": 63.5,
    },
]


def _nur_lesend(mock: AiohttpClientMocker) -> None:
    """Dieselbe Kulisse, gesehen durch einen Nur-Lese-Schlüssel."""
    from .conftest import ANALYSIS, PLAYING, SERVERS

    mock.get(f"{URL}/api/v1/me", json=IDENTITY_READONLY)
    mock.get(f"{URL}/api/v1/dashboard", json=TILE)
    mock.get(f"{URL}/api/settings/channels/webhook/targets", json=[])
    mock.get(f"{URL}/api/admin/analyse", json=ANALYSIS)
    mock.get(f"{URL}/api/settings/qualitaetsprofile/medienserver", json=SERVERS)
    mock.get(f"{URL}/api/admin/analyse/laufend", json=PLAYING)
    mock.get(f"{URL}/api/admin/stats", json={"users": []})
    mock.get(f"{URL}/api/calendar", json={"days": []})
    mock.get(f"{URL}/api/v1/about", json=ABOUT)


def _volle_kulisse(mock: AiohttpClientMocker) -> None:
    """Alles, was ein Betreiber-Schlüssel beim Einrichten abfragt.

    ⚠️ Als Funktion, weil manche Tests die Anfragenliste vorher ersetzen
    müssen und der Mock den ersten Treffer nimmt.
    """
    from .conftest import ANALYSIS, IDENTITY_ADMIN, PLAYING, SERVERS, STATS, TILE

    mock.get(f"{URL}/api/v1/me", json=IDENTITY_ADMIN)
    mock.get(f"{URL}/api/v1/dashboard", json=TILE)
    mock.get(f"{URL}/api/v1/admin/requests/pending/count", json={"pending": 4})
    mock.get(f"{URL}/api/settings/channels/webhook/targets", json=[])
    mock.get(f"{URL}/api/admin/analyse", json=ANALYSIS)
    mock.get(f"{URL}/api/settings/qualitaetsprofile/medienserver", json=SERVERS)
    mock.get(f"{URL}/api/admin/analyse/laufend", json=PLAYING)
    mock.get(f"{URL}/api/admin/stats", json=STATS)
    mock.get(f"{URL}/api/calendar", json={"days": []})
    mock.get(f"{URL}/api/v1/about", json=ABOUT)


@pytest.fixture(autouse=True)
def no_webhook_enrolment():
    with patch(
        "custom_components.nexview.webhook.NexviewWebhook.async_ensure_target",
        AsyncMock(return_value=True),
    ):
        yield


class TestCalendar:
    async def test_the_next_release_shows_up(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "calendar", DOMAIN, f"{entry.entry_id}_calendar"
        )
        assert entity_id, "No calendar was created"

        events = await hass.services.async_call(
            "calendar",
            "get_events",
            {
                "entity_id": entity_id,
                "start_date_time": dt_util.parse_datetime("2026-09-01 00:00:00"),
                "end_date_time": dt_util.parse_datetime("2026-09-30 00:00:00"),
            },
            blocking=True,
            return_response=True,
        )
        found = events[entity_id]["events"]
        assert [e["summary"] for e in found] == ["Some Film"]
        # ⚠️ All day, and ending the following day. Ending on the same one
        # would be a zero-length event that no card draws.
        assert found[0]["start"] == "2026-09-10"
        assert found[0]["end"] == "2026-09-11"


class TestUpdate:
    async def test_it_says_which_version_is_waiting(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "update", DOMAIN, f"{entry.entry_id}_update"
        )
        state = hass.states.get(entity_id)
        assert state.state == "on", "An update is pending, so this has to be on."
        assert state.attributes["installed_version"] == "0.30.0"
        assert state.attributes["latest_version"] == "0.31.0"


class TestButtons:
    async def test_an_errand_reaches_nexview(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ There from the start, but not on the dashboard.

        These carry the configuration category, which keeps them off the
        overview and puts them on the device card - where somebody looks for
        controls. Disabling them on top of that made the only buttons this
        integration has invisible, which is how it read as a viewer.
        """
        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "button", DOMAIN, f"{entry.entry_id}_storage_sync"
        )
        assert entity_id, "The button has to exist."
        assert hass.states.get(entity_id) is not None, "And it has to be usable."

        with patch(
            "custom_components.nexview.api.NexviewClient.storage_sync", AsyncMock()
        ) as sync:
            await hass.services.async_call(
                "button", "press", {"entity_id": entity_id}, blocking=True
            )
        sync.assert_awaited_once()

    async def test_a_read_only_key_gets_no_buttons(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        """⚠️ Not greyed out - not there.

        Every button here changes something, and a key that may not write
        would answer 403 to all of them. A row of controls that cannot work is
        worse than no row at all.
        """
        _nur_lesend(aioclient_mock)

        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        buttons = [
            e
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
            if e.domain == "button"
        ]
        assert buttons == []


class TestActionsThatAnswer:
    async def test_listing_requests_returns_them(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        nexview.clear_requests()
        _volle_kulisse(nexview)
        nexview.get(f"{URL}/api/admin/requests", json=REQUESTS)
        await setup_entry(hass, entry)

        answer = await hass.services.async_call(
            DOMAIN, SERVICE_LIST_REQUESTS, {}, blocking=True, return_response=True
        )

        rows = answer["requests"]
        assert [r["id"] for r in rows] == [41, 42]
        assert rows[1]["progress"] == 63.5

    async def test_the_answer_leaves_the_private_parts_behind(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Nexview answers with more than belongs in an automation.

        Avatars, ratings, the storage figures of whoever asked, and the name of
        a child a request was made for. Action responses end up in traces and
        in whatever an automation does with them, so the client cuts them out
        before they ever reach Home Assistant.
        """
        nexview.clear_requests()
        _volle_kulisse(nexview)
        nexview.get(f"{URL}/api/admin/requests", json=REQUESTS)
        await setup_entry(hass, entry)

        answer = await hass.services.async_call(
            DOMAIN, SERVICE_LIST_REQUESTS, {}, blocking=True, return_response=True
        )

        text = str(answer)
        assert "avatar" not in text
        assert "Kind" not in text, "A child's name reached Home Assistant."

    async def test_active_downloads_are_the_running_ones(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        nexview.clear_requests()
        _volle_kulisse(nexview)
        nexview.get(f"{URL}/api/admin/requests", json=REQUESTS)
        await setup_entry(hass, entry)

        answer = await hass.services.async_call(
            DOMAIN, SERVICE_ACTIVE_DOWNLOADS, {}, blocking=True, return_response=True
        )

        assert [d["id"] for d in answer["downloads"]] == [42]

    async def test_allowances_come_back_with_both_kinds(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """Both allowances always apply in Nexview, so both are always answered."""
        await setup_entry(hass, entry)

        answer = await hass.services.async_call(
            DOMAIN, SERVICE_GET_QUOTA, {"account_id": 7}, blocking=True,
            return_response=True,
        )

        konto = answer["accounts"][0]
        assert konto["name"] == "Gast"
        assert konto["movies"] == {"used": 4, "limit": 5, "remaining": 1}
        assert konto["storage_bytes"]["remaining"] == 500_000_000_000

    async def test_searching_needs_no_right_to_decide(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        """⚠️ Reading is not deciding.

        A read-only key may not approve anything, and the deciding actions say
        so. Looking a title up changes nothing, and refusing that would be an
        invented restriction.
        """
        _nur_lesend(aioclient_mock)
        aioclient_mock.get(
            f"{URL}/api/v1/search/movie", json={"results": [{"title": "Some Film"}]}
        )

        await setup_entry(hass, entry)

        answer = await hass.services.async_call(
            DOMAIN,
            SERVICE_SEARCH,
            {"query": "Some Film"},
            blocking=True,
            return_response=True,
        )
        assert answer["results"] == [{"title": "Some Film"}]
