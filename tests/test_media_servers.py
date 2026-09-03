"""Medienserver, Warteschlangen und die Werte, die vorher fehlten.

⚠️ **Was hier nicht geprüft wird, weil es nicht gebaut ist:** Namen von
Zuschauern in Entitäten. Nexview weiß, wer gerade was auf welchem Gerät
schaut, und ein Sensor mit dieser Angabe wäre bequem und dauerhaft. Er stünde
dann in einer Datenbank, die alles jahrelang behält. Deshalb gibt es dafür eine
Aktion, und der letzte Test hier hält fest, dass sie es ist.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.nexview.const import CONF_ACCOUNTS, DOMAIN, SERVICE_NOW_PLAYING

from .conftest import URL, setup_entry


@pytest.fixture(autouse=True)
def no_webhook_enrolment():
    with patch(
        "custom_components.nexview.webhook.NexviewWebhook.async_ensure_target",
        AsyncMock(return_value=True),
    ):
        yield


def _state(hass: HomeAssistant, entry: MockConfigEntry, unique: str, domain="sensor"):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{unique}")
    assert entity_id, f"Keine Entität für {unique}"
    return hass.states.get(entity_id)


class TestMediaServers:
    async def test_each_server_becomes_a_device(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        await setup_entry(hass, entry)

        devices = dr.async_get(hass)
        plex = devices.async_get_device_by_identifier(
            (DOMAIN, f"{entry.entry_id}_server1"), entry.entry_id
        )
        assert plex is not None
        assert plex.name == "Wohnzimmer"
        # ⚠️ Der Hersteller ist Plex, nicht nexapps. Der Server gehört dem,
        # der ihn betreibt; Nexview redet nur mit ihm.
        assert plex.manufacturer == "Plex"

    async def test_it_counts_what_is_playing_and_what_is_being_converted(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """Zwei Wiedergaben auf Plex, eine davon umgerechnet."""
        await setup_entry(hass, entry)

        assert _state(hass, entry, "server1_playing").state == "2"
        assert _state(hass, entry, "server1_transcoding").state == "1"
        assert _state(hass, entry, "server1_titles").state == "3723"

    async def test_a_server_without_a_count_still_counts_streams(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Jellyfin läuft nichts, und der Abgleich kennt es trotzdem.

        Umgekehrt gilt dasselbe: Ein Server, dessen Bestand noch nie
        verglichen wurde, hat keine Titelzahl, und seine beiden anderen Werte
        stimmen trotzdem.
        """
        await setup_entry(hass, entry)

        assert _state(hass, entry, "server2_playing").state == "0"
        assert _state(hass, entry, "server2_titles").state == "3731"


class TestWhatWasMissing:
    async def test_the_queue_and_the_stuck_half_of_it(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Beide Zahlen, weil die zweite die interessante ist.

        Eine lange Warteschlange ist ein voller Abend. Eine hängende merkt
        niemand, bis sich jemand beschwert.
        """
        await setup_entry(hass, entry)

        assert _state(hass, entry, "radarr-standard_queue").state == "2"
        assert _state(hass, entry, "radarr-standard_queue_stuck").state == "0"

    async def test_whether_an_instance_calls_back(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """Radarr ruft zurück, Sonarr nicht. Ohne das pollt Nexview."""
        await setup_entry(hass, entry)

        radarr = _state(hass, entry, "radarr-standard_webhook_active", "binary_sensor")
        sonarr = _state(hass, entry, "sonarr-standard_webhook_active", "binary_sensor")
        assert radarr.state == "on"
        assert sonarr.state == "off"

    async def test_open_requests_per_account(
        self, hass: HomeAssistant, nexview: AiohttpClientMocker
    ) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=f"{URL}::1",
            data={"url": URL, "api_key": "nxv_" + "t" * 40, "webhook_id": "w"},
            options={CONF_ACCOUNTS: ["7"]},
        )
        await setup_entry(hass, entry)

        assert _state(hass, entry, "account7_open_requests").state == "2"

    async def test_nothing_waiting_means_no_waiting_time(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Keine wartende Anfrage ist nicht null Stunden.

        Eine Null läse sich als „gerade eben hat jemand gefragt", also als das
        Gegenteil einer leeren Warteschlange. Der Eintrag sagt stattdessen
        nichts.
        """
        await setup_entry(hass, entry)

        assert _state(hass, entry, "oldest_pending").state == "unavailable"


class TestWhoIsWatchingStaysAnAction:
    async def test_the_details_come_from_an_action(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        await setup_entry(hass, entry)

        answer = await hass.services.async_call(
            DOMAIN, SERVICE_NOW_PLAYING, {}, blocking=True, return_response=True
        )

        laeuft = answer["playing"]
        assert len(laeuft) == 2
        assert laeuft[0]["account"] == "Alex"
        assert laeuft[0]["transcoding"] is False
        assert laeuft[1]["transcoding"] is True

    async def test_no_entity_carries_a_name(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Der Punkt der ganzen Datei.

        Home Assistant schreibt jeden Zustand und jedes Attribut in seine
        Langzeitdatenbank. Wer wann was geschaut hat, gehört dort nicht hin -
        auch dann nicht, wenn es auf einem Wandtablett hübsch aussähe.
        """
        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        for eintrag in er.async_entries_for_config_entry(registry, entry.entry_id):
            zustand = hass.states.get(eintrag.entity_id)
            if zustand is None:
                continue
            text = f"{zustand.state} {zustand.attributes}"
            assert "Alex" not in text, f"Ein Name steht in {eintrag.entity_id}"
            assert "Sam" not in text, f"Ein Name steht in {eintrag.entity_id}"
            assert "Some Episode" not in text, f"Ein Titel steht in {eintrag.entity_id}"
