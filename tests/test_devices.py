"""The devices below Nexview: one per instance, one per chosen account.

⚠️ **Accounts are opt-in, and that is the point being checked here.** An
installation with thirty accounts must not be handed two hundred entities by an
integration it just installed, and every account somebody adds in Nexview must
not quietly add more.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.nexview.const import CONF_ACCOUNTS, DOMAIN

from .conftest import setup_entry


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
    assert entity_id, f"No entity for {unique}"
    return hass.states.get(entity_id)


class TestInstances:
    async def test_each_arr_becomes_its_own_device(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        await setup_entry(hass, entry)

        devices = dr.async_get(hass)
        radarr = devices.async_get_device_by_identifier(
            (DOMAIN, f"{entry.entry_id}_radarr-standard"), entry.entry_id
        )
        assert radarr is not None
        assert radarr.name == "Radarr"
        assert radarr.model == "Radarr"
        assert radarr.sw_version == "6.3.0"

        # ⚠️ Hanging off Nexview, not floating beside it. Home Assistant draws
        # the chain from this, and without it the instances look like separate
        # products that happen to share a name.
        main = devices.async_get_device_by_identifier(
            (DOMAIN, entry.entry_id), entry.entry_id
        )
        assert radarr.via_device_id == main.id

    async def test_an_unreachable_instance_says_so_and_keeps_its_problems(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        await setup_entry(hass, entry)

        radarr = _state(hass, entry, "radarr-standard_reachable", "binary_sensor")
        sonarr = _state(hass, entry, "sonarr-standard_reachable", "binary_sensor")
        assert radarr.state == "on"
        assert sonarr.state == "off"
        assert _state(hass, entry, "sonarr-standard_problems").state == "1"
        assert _state(hass, entry, "radarr-standard_problems").state == "0"


class TestAccounts:
    async def test_nobody_gets_entities_without_being_picked(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ The default has to be nothing, not everything."""
        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        keys = {
            e.unique_id.removeprefix(f"{entry.entry_id}_")
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        }
        assert not any(k.startswith("account") for k in keys), (
            "Accounts appeared although nobody picked any."
        )

    async def test_a_picked_account_brings_its_allowances(
        self, hass: HomeAssistant, nexview: AiohttpClientMocker
    ) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Nexview (Admin)",
            unique_id="http://nexview.test:8000::1",
            data={
                "url": "http://nexview.test:8000",
                "api_key": "nxv_" + "t" * 40,
                "webhook_id": "w",
            },
            options={CONF_ACCOUNTS: ["7"]},
        )
        await setup_entry(hass, entry)

        assert _state(hass, entry, "account7_movie_quota_used").state == "4"
        assert _state(hass, entry, "account7_movie_quota_remaining").state == "1"
        assert _state(hass, entry, "account7_series_quota_remaining").state == "0"

        devices = dr.async_get(hass)
        konto = devices.async_get_device_by_identifier(
            (DOMAIN, f"{entry.entry_id}_account7"), entry.entry_id
        )
        assert konto is not None and konto.name == "Gast"

    async def test_an_unlimited_allowance_is_not_zero(
        self, hass: HomeAssistant, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ The mistake worth guarding against.

        Where Nexview grants unlimited, there is no number left over. Showing
        a nought would read as an account that has used everything up - the
        exact opposite of the truth.
        """
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="http://nexview.test:8000::1",
            data={
                "url": "http://nexview.test:8000",
                "api_key": "nxv_" + "t" * 40,
                "webhook_id": "w",
            },
            options={CONF_ACCOUNTS: ["1"]},
        )
        await setup_entry(hass, entry)

        assert _state(hass, entry, "account1_movie_quota_used").state == "2"
        offen = _state(hass, entry, "account1_movie_quota_remaining")
        assert offen.state == "unavailable"

    async def test_a_full_allowance_shows_up_as_a_problem(
        self, hass: HomeAssistant, nexview: AiohttpClientMocker
    ) -> None:
        """Guest has three of three series used, so requesting is over for now."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="http://nexview.test:8000::1",
            data={
                "url": "http://nexview.test:8000",
                "api_key": "nxv_" + "t" * 40,
                "webhook_id": "w",
            },
            options={CONF_ACCOUNTS: ["1", "7"]},
        )
        await setup_entry(hass, entry)

        gast = _state(hass, entry, "account7_quota_exhausted", "binary_sensor")
        admin = _state(hass, entry, "account1_quota_exhausted", "binary_sensor")
        assert gast.state == "on"
        assert admin.state == "off"
