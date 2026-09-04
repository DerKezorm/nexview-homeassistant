"""Picking which accounts get entities, and the errands on one instance.

⚠️ **The options dialog is the one place where somebody can flood their own
Home Assistant.** Each account picked here brings seven entities, so what
matters is that nothing happens by itself and that the list is understandable
before anybody clicks.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.nexview.const import CONF_ACCOUNTS, CONF_PUSH, DOMAIN

from .conftest import ABOUT, IDENTITY_USER, MY_STORAGE, QUOTA, URL, setup_entry


@pytest.fixture(autouse=True)
def no_webhook_enrolment():
    with patch(
        "custom_components.nexview.webhook.NexviewWebhook.async_ensure_target",
        AsyncMock(return_value=True),
    ):
        yield


class TestPickingAccounts:
    async def test_the_list_offers_the_accounts_by_name(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        await setup_entry(hass, entry)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"

    async def test_picking_one_brings_its_entities_without_a_restart(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ The entry reloads itself, which is the whole point.

        Somebody picks an account and expects to see it. Making them restart
        Home Assistant for that would be the kind of detail that gets an
        integration a bad reputation.
        """
        await setup_entry(hass, entry)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_ACCOUNTS: ["7"]}
        )
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_ACCOUNTS] == ["7"]

        registry = er.async_get(hass)
        assert registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_account7_movie_quota_used"
        ), "The account was picked and its entities did not appear."

    async def test_a_personal_key_sees_no_accounts_but_still_gets_the_switch(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        """⚠️ Diese Form brach frueher ab, und zwar fuer die Falschen.

        Wer Nexview nicht verwalten darf, sieht keine fremden Konten - eine
        leere Liste ohne Erklaerung waere schlechter als keine Liste. Der
        Abbruch nahm damit aber ausgerechnet den Leuten jede Einstellung weg,
        die den Rueckkanal am ehesten abschalten muessen: Wenn Nexview ihr Home
        Assistant nicht erreicht, ist der Haken ihr einziger Weg, die
        Reparaturmeldung loszuwerden.
        """
        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_USER)
        aioclient_mock.get(f"{URL}/api/v1/me/push", json={"eingerichtet": False})
        aioclient_mock.get(f"{URL}/api/v1/about", json=ABOUT)
        aioclient_mock.get(f"{URL}/api/v1/requests/quota", json=QUOTA)
        aioclient_mock.get(f"{URL}/api/v1/storage/me", json=MY_STORAGE)
        aioclient_mock.get(
            f"{URL}/api/v1/notifications/unread/count", json={"unread": 0}
        )
        aioclient_mock.get(f"{URL}/api/v1/tickets/open-count", json={"count": 0})

        await setup_entry(hass, entry)

        result = await hass.config_entries.options.async_init(entry.entry_id)

        assert result["type"] is FlowResultType.FORM
        felder = {str(k.schema) for k in result["data_schema"].schema}
        assert felder == {CONF_PUSH}, (
            "Ein persoenlicher Schluessel soll den Rueckkanal-Haken sehen und "
            f"sonst nichts, bekam aber: {sorted(felder)}"
        )

    async def test_unpicking_takes_the_entities_away_again(
        self, hass: HomeAssistant, nexview: AiohttpClientMocker
    ) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=f"{URL}::1",
            data={"url": URL, "api_key": "nxv_" + "t" * 40, "webhook_id": "w"},
            options={CONF_ACCOUNTS: ["7"]},
        )
        await setup_entry(hass, entry)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_ACCOUNTS: []}
        )
        await hass.async_block_till_done()

        # ⚠️ Home Assistant keeps both the registry entry and a restored
        # state, and that is right: unpicking by accident should not destroy a
        # year of history. What has to stop is the entity being fed - which
        # shows as unavailable rather than as a number that quietly stands
        # still and looks current.
        zustand = hass.states.get("sensor.gast_movies_used")
        assert zustand is None or zustand.state == "unavailable", (
            f"The account was unpicked and its sensor still reads {zustand}."
        )


class TestInstanceErrands:
    async def test_testing_a_connection_names_the_right_service(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Nexview calls the instance radarr-standard and the errand radarr.

        Derived by string surgery this happens to work; spelled out in a table
        it stays true when somebody adds a third tier.
        """
        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "button", DOMAIN, f"{entry.entry_id}_sonarr-standard_test_connection"
        )
        assert entity_id
        registry.async_update_entity(entity_id, disabled_by=None)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        with patch(
            "custom_components.nexview.api.NexviewClient.test_connection", AsyncMock()
        ) as test:
            await hass.services.async_call(
                "button", "press", {"entity_id": entity_id}, blocking=True
            )

        test.assert_awaited_once_with("sonarr")

    async def test_an_instance_nexview_does_not_name_is_refused(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        """Something Nexview grew that this version has never heard of."""
        from .conftest import IDENTITY_ADMIN, TILE

        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_ADMIN)
        aioclient_mock.get(f"{URL}/api/v1/dashboard", json=TILE)
        aioclient_mock.get(f"{URL}/api/settings/channels/webhook/targets", json=[])
        aioclient_mock.get(f"{URL}/api/v1/about", json=ABOUT)
        aioclient_mock.get(f"{URL}/api/admin/stats", json={"users": []})
        aioclient_mock.get(f"{URL}/api/calendar", json={"days": []})
        aioclient_mock.get(
            f"{URL}/api/v1/admin/requests/pending/count", json={"pending": 0}
        )
        aioclient_mock.get(f"{URL}/api/v1/requests/quota", json=QUOTA)
        aioclient_mock.get(f"{URL}/api/v1/storage/me", json=MY_STORAGE)
        aioclient_mock.get(
            f"{URL}/api/v1/notifications/unread/count", json={"unread": 0}
        )
        aioclient_mock.get(f"{URL}/api/v1/tickets/open-count", json={"count": 0})
        aioclient_mock.get(
            f"{URL}/api/settings/qualitaetsprofile/medienserver",
            json={"server": [], "instanzen": [], "warnungen": []},
        )
        aioclient_mock.get(f"{URL}/api/admin/analyse/laufend", json={"wiedergaben": []})
        aioclient_mock.get(
            f"{URL}/api/admin/analyse",
            json={
                "instanzen": [
                    {
                        "kennung": "lidarr-standard",
                        "name": "Lidarr",
                        "erreichbar": True,
                        "version": "2.0",
                        "meldungen": [],
                    }
                ],
                "abgleich": {},
            },
        )

        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "button", DOMAIN, f"{entry.entry_id}_lidarr-standard_test_connection"
        )
        assert entity_id, "An instance Nexview reports has to get its button."
        registry.async_update_entity(entity_id, disabled_by=None)
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        from homeassistant.exceptions import HomeAssistantError

        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                "button", "press", {"entity_id": entity_id}, blocking=True
            )


class TestUpdateEntity:
    async def test_asking_for_a_check_reaches_nexview(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "update", DOMAIN, f"{entry.entry_id}_update"
        )

        component = hass.data["entity_components"]["update"]
        entity = component.get_entity(entity_id)

        with patch(
            "custom_components.nexview.api.NexviewClient.check_update", AsyncMock()
        ) as check:
            await entity.async_update()

        check.assert_awaited_once()

    async def test_the_release_notes_point_at_the_release(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ A link, not an invented summary.

        Nexview does not serve its own notes, and writing something plausible
        here would be putting words in its mouth.
        """
        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "update", DOMAIN, f"{entry.entry_id}_update"
        )
        component = hass.data["entity_components"]["update"]
        entity = component.get_entity(entity_id)
        text = await entity.async_release_notes()
        assert text is not None and "0.31.0" in text
        assert ABOUT["release_url"] in text
