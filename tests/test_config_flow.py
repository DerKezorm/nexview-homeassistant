"""The setup dialog.

⚠️ **Every wrong answer gets its own sentence.** A dialog that says "cannot
connect" to a revoked key, a typo and a pasted password alike sends people
looking in the log for what the dialog already knew.
"""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.nexview.const import CONF_KEY, CONF_URL, CONF_WEBHOOK_ID, DOMAIN

from .conftest import IDENTITY_ADMIN, IDENTITY_USER, KEY, URL


async def _start(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


class TestAddingOne:
    async def test_a_good_key_creates_an_entry(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_ADMIN)

        result = await _start(hass)
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: URL, CONF_KEY: KEY}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Nexview (Admin)"
        assert result["data"][CONF_URL] == URL
        assert result["data"][CONF_KEY] == KEY
        # ⚠️ Made once and kept. A new address on every restart would leave a
        # trail of dead targets in Nexview that nobody knows how to clean up.
        assert result["data"][CONF_WEBHOOK_ID]

    async def test_the_address_is_tidied_not_rejected(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        """People paste an address without a scheme and with a trailing slash."""
        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_ADMIN)

        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: "nexview.test:8000/", CONF_KEY: KEY}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_URL] == URL

    async def test_the_same_account_cannot_be_added_twice(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_ADMIN)
        MockConfigEntry(
            domain=DOMAIN, unique_id=f"{URL}::1", data={CONF_URL: URL, CONF_KEY: KEY}
        ).add_to_hass(hass)

        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: URL, CONF_KEY: KEY}
        )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"

    async def test_a_second_account_on_the_same_nexview_is_fine(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        """⚠️ The address alone is not the identity.

        One household may reasonably connect the same Nexview twice: once with
        an operator key for the house figures, once with a personal key. Only
        the same account twice is a mistake.
        """
        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_USER)
        MockConfigEntry(
            domain=DOMAIN, unique_id=f"{URL}::1", data={CONF_URL: URL, CONF_KEY: KEY}
        ).add_to_hass(hass)

        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: URL, CONF_KEY: KEY}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Nexview (Gast)"


class TestWhatGoesWrong:
    async def test_a_password_is_named_as_such(self, hass: HomeAssistant) -> None:
        """⚠️ Caught before anything is sent.

        Somebody who types their password here would otherwise get "rejected",
        which is true and useless: it does not say that this field wants
        something else entirely.
        """
        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: URL, CONF_KEY: "hunter2"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "not_a_key"}

    async def test_a_revoked_key_says_so(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        aioclient_mock.get(f"{URL}/api/v1/me", status=401)

        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: URL, CONF_KEY: KEY}
        )

        assert result["errors"] == {"base": "invalid_auth"}

    async def test_an_old_nexview_says_so(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        """⚠️ Recognised by the missing address, not by the version number.

        Comparing version strings means parsing them, and being wrong about a
        release candidate or somebody's fork. A Nexview without /api/v1/me is
        too old, full stop.
        """
        aioclient_mock.get(f"{URL}/api/v1/me", status=404)

        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: URL, CONF_KEY: KEY}
        )

        assert result["errors"] == {"base": "too_old"}

    async def test_a_silent_address_says_so(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        import aiohttp

        aioclient_mock.get(f"{URL}/api/v1/me", exc=aiohttp.ClientConnectionError())

        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: URL, CONF_KEY: KEY}
        )

        assert result["errors"] == {"base": "cannot_connect"}


class TestSigningInAgain:
    async def test_a_new_key_replaces_the_old_one(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_ADMIN)
        entry.add_to_hass(hass)

        result = await entry.start_reauth_flow(hass)
        assert result["type"] is FlowResultType.FORM

        new_key = "nxv_" + "n" * 40
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_KEY: new_key}
        )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        assert entry.data[CONF_KEY] == new_key

    async def test_a_key_from_another_account_is_refused(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        """⚠️ Otherwise re-auth quietly turns one entry into a different one.

        Every entity would keep its name and its history while suddenly
        meaning somebody else's account.
        """
        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_USER)
        entry.add_to_hass(hass)

        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_KEY: "nxv_" + "x" * 40}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "wrong_account"}
        assert entry.data[CONF_KEY] == KEY, "The old key must stay untouched."
