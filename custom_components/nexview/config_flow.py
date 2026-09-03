"""Setting it up: an address, a key, done.

⚠️ **The key is not a password.** Nexview issues named access keys that can be
revoked one at a time, carry an expiry date and can be marked read only. Asking
for a username and password here would put a full login into Home Assistant's
configuration, break the moment two-factor or single sign-on is switched on,
and leave nothing to revoke afterwards.

⚠️ **The connection is tested before anything is saved.** A dialog that
accepts a typo and produces a broken entry sends people looking in the log for
what the dialog already knew.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    KEY_PREFIX,
    MIN_VERSION,
    Identity,
    NexviewAuthError,
    NexviewClient,
    NexviewConnectionError,
    NexviewError,
    NexviewTooOldError,
)
from .const import CONF_KEY, CONF_URL, CONF_WEBHOOK_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Required(CONF_KEY): str,
    }
)

STEP_REAUTH = vol.Schema({vol.Required(CONF_KEY): str})


class NexviewConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask, check, save."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            url = _tidy_url(user_input[CONF_URL])
            key = user_input[CONF_KEY].strip()
            identity, error = await self._check(url, key)

            if error:
                errors["base"] = error
            elif identity is not None:
                # ⚠️ Address **and** account. The same Nexview may legitimately
                # be added twice - once with an operator key for the house
                # figures, once with a personal key - but never the same
                # account twice.
                await self.async_set_unique_id(f"{url}::{identity.account.id}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Nexview ({identity.account.name})",
                    data={
                        CONF_URL: url,
                        CONF_KEY: key,
                        # Made here so the address stays the same across
                        # restarts. Nexview stores it on its side, and a new
                        # one every boot would leave dead targets over there.
                        CONF_WEBHOOK_ID: webhook.async_generate_id(),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER,
            errors=errors,
            description_placeholders={"min_version": MIN_VERSION},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Nexview rejected the key. Ask for a new one, keep everything else."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            key = user_input[CONF_KEY].strip()
            identity, error = await self._check(entry.data[CONF_URL], key)

            if error:
                errors["base"] = error
            elif identity is not None:
                # ⚠️ The new key has to belong to the same account. Otherwise a
                # re-auth would quietly turn one entry into a different one,
                # and every entity would keep its name while meaning something
                # else.
                if f"{entry.data[CONF_URL]}::{identity.account.id}" != entry.unique_id:
                    errors["base"] = "wrong_account"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_KEY: key}
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH,
            errors=errors,
            description_placeholders={"name": entry.title},
        )

    async def _check(self, url: str, key: str) -> tuple[Identity | None, str | None]:
        """Try the connection. Returns either what we found or why we did not."""
        if not key.startswith(KEY_PREFIX):
            # Caught before anything is sent: this is almost always a password
            # or a pasted session token, and Nexview would answer 401 without
            # ever saying which of the two fields was wrong.
            return None, "not_a_key"

        client = NexviewClient(async_get_clientsession(self.hass), url, key)
        try:
            return await client.identity(), None
        except NexviewTooOldError:
            return None, "too_old"
        except NexviewAuthError:
            return None, "invalid_auth"
        except NexviewConnectionError:
            return None, "cannot_connect"
        except NexviewError:
            _LOGGER.exception("Unexpected answer from Nexview at %s", url)
            return None, "unknown"


def _tidy_url(raw: str) -> str:
    """Make what somebody typed into something that can be called.

    People paste ``nexview.example.com``, ``http://nexview:8000/`` and
    ``http://nexview:8000/requests`` with equal confidence. Only the scheme
    and the trailing slash are worth fixing quietly; a path is left alone,
    because Nexview may well live behind one.
    """
    url = raw.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    return url
