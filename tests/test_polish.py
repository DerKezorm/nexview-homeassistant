"""Diagnostics, system health, and changing the address without starting over.

⚠️ **The diagnostics test is the important one here.** That file gets attached
to public issue reports by people who want help, and it stays there. If a key
or an address ever leaks into it, it leaks to everybody who reads the issue.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.nexview.const import CONF_KEY, CONF_URL, DOMAIN
from custom_components.nexview.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import IDENTITY_ADMIN, IDENTITY_USER, KEY, URL, WEBHOOK_ID, setup_entry


@pytest.fixture(autouse=True)
def no_webhook_enrolment():
    with patch(
        "custom_components.nexview.webhook.NexviewWebhook.async_ensure_target",
        AsyncMock(return_value=True),
    ):
        yield


class TestDiagnostics:
    async def test_nothing_secret_comes_out(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Three secrets, and all three have to be gone.

        The key is obvious. The address is not: it says where somebody's
        installation lives. And the webhook id is a secret in its own right -
        anybody holding it can post events into that Home Assistant.
        """
        await setup_entry(hass, entry)

        report = str(await async_get_config_entry_diagnostics(hass, entry))

        assert KEY not in report, "The access key was in the diagnostics."
        assert URL not in report, "The address of the installation was in there."
        assert WEBHOOK_ID not in report, "The webhook id was in there."
        assert "REDACTED" in report, "Nothing was redacted at all - is the list right?"

    async def test_it_answers_the_questions_that_help(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """What a missing entity actually comes down to: what the key may do."""
        await setup_entry(hass, entry)

        report = await async_get_config_entry_diagnostics(hass, entry)

        assert report["key"]["may"] == [
            "anfragen",
            "einrichten",
            "entscheiden",
            "lesen",
            "verwalten",
        ]
        assert report["key"]["read_only"] is False
        assert report["what_was_read"]["tile"] is True
        assert report["what_was_read"]["instances"] == 2
        assert report["connection"]["nexview_version"] == "0.30.0"

    async def test_no_names_of_people_or_titles(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Findings come as identifiers, instances as keys, accounts as a count.

        Nexview knows plenty that would be handy in a bug report and has no
        business in one: who requested what, what the operator called their
        instances, who has how much left.
        """
        await setup_entry(hass, entry)

        report = str(await async_get_config_entry_diagnostics(hass, entry))

        assert "Gast" not in report, "An account name reached the diagnostics."
        assert "Some Film" not in report, "A requested title reached the diagnostics."


class TestSystemHealth:
    async def test_it_says_whether_events_are_arriving(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """The one line worth having: everything works without the push, quietly worse."""
        from custom_components.nexview.system_health import system_health_info

        await setup_entry(hass, entry)

        info = await system_health_info(hass)
        assert info["connected"] == 1
        assert info["answering"] == 1
        assert info["receiving_events"] == 1
        assert info["nexview_version"] == "0.30.0"

    async def test_it_survives_having_nothing_connected(
        self, hass: HomeAssistant
    ) -> None:
        from custom_components.nexview.system_health import system_health_info

        assert await system_health_info(hass) == {"connected": 0}


class TestReconfigure:
    async def test_a_moved_nexview_keeps_its_entry(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        """⚠️ Moving must not cost anybody their history.

        A new port, a name instead of an IP, a proxy in front - all of that is
        the same Nexview, and re-adding it from scratch would leave every
        sensor starting from nothing.
        """
        neu = "http://nexview.example.com:8000"
        aioclient_mock.get(f"{neu}/api/v1/me", json=IDENTITY_ADMIN)
        entry.add_to_hass(hass)

        result = await entry.start_reconfigure_flow(hass)
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: neu, CONF_KEY: KEY}
        )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.data[CONF_URL] == neu
        assert entry.unique_id == f"{neu}::1"

    async def test_it_refuses_to_become_a_different_account(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        """Otherwise every entity would keep its past while meaning somebody else."""
        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_USER)
        entry.add_to_hass(hass)

        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: URL, CONF_KEY: "nxv_" + "z" * 40}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "wrong_account"}
        assert entry.data[CONF_KEY] == KEY, "The old key must stay untouched."


class TestRemovingDevices:
    async def test_a_gone_instance_may_be_deleted(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Only what Nexview no longer has.

        Nothing is removed automatically, because an instance that vanished for
        a moment - somebody is editing settings - comes back with its history.
        But one taken out for good would otherwise sit in the list forever.
        """
        from custom_components.nexview import async_remove_config_entry_device

        await setup_entry(hass, entry)
        devices = dr.async_get(hass)

        sonarr = devices.async_get_device_by_identifier(
            (DOMAIN, f"{entry.entry_id}_sonarr-standard"), entry.entry_id
        )
        assert not await async_remove_config_entry_device(hass, entry, sonarr), (
            "Nexview still has this instance, so it must not be removable."
        )

        weg = devices.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{entry.entry_id}_sonarr-uhd")},
            name="Sonarr 4K",
        )
        assert await async_remove_config_entry_device(hass, entry, weg)

    async def test_nexview_itself_stays(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """Deleting the entry is how you get rid of Nexview, not deleting a device."""
        from custom_components.nexview import async_remove_config_entry_device

        await setup_entry(hass, entry)
        devices = dr.async_get(hass)
        main = devices.async_get_device_by_identifier(
            (DOMAIN, entry.entry_id), entry.entry_id
        )

        assert not await async_remove_config_entry_device(hass, entry, main)


class TestSayingSoWhenSomethingStops:
    async def test_a_lasting_outage_is_reported_once_and_its_return_too(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        caplog,
    ) -> None:
        """⚠️ Once, not every thirty seconds.

        A log line repeated all night buries whatever else went wrong that
        night. But saying nothing at all leaves an entity unavailable with no
        explanation anywhere - so the first failure is a warning, and so is the
        recovery.
        """
        from custom_components.nexview.api import NexviewConnectionError

        await setup_entry(hass, entry)
        coordinator = entry.runtime_data

        with patch(
            "custom_components.nexview.api.NexviewClient.tile",
            AsyncMock(side_effect=NexviewConnectionError("no answer")),
        ):
            caplog.clear()
            await coordinator.async_refresh()
            erste = caplog.text.count("stopped answering")

            await coordinator.async_refresh()
            zweite = caplog.text.count("stopped answering")

        assert erste == 1, "The first failure has to be said out loud."
        assert zweite == 1, "The second one must not repeat it."

        caplog.clear()
        await coordinator.async_refresh()
        assert "answering for the dashboard again" in caplog.text, (
            "Coming back has to be reported too - that half is usually forgotten."
        )
