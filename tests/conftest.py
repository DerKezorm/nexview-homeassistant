"""Shared setup for the tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.nexview.const import CONF_KEY, CONF_URL, CONF_WEBHOOK_ID, DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"

URL = "http://nexview.test:8000"
KEY = "nxv_" + "t" * 40
WEBHOOK_ID = "nexview-test-webhook"

#: What ``GET /api/v1/me`` answers for an operator whose key may everything.
IDENTITY_ADMIN: dict[str, Any] = {
    "version": "0.30.0",
    "konto": {
        "id": 1,
        "username": "admin",
        "name": "Admin",
        "role": "admin",
        "betreiber": True,
    },
    "schluessel": {"name": "Home Assistant", "nur_lesen": False},
    "darf": ["lesen", "anfragen", "entscheiden", "verwalten", "einrichten"],
}

#: The same account, but the key may only read. Everything that changes
#: something is gone, and ``verwalten`` stays - that is the whole point of the
#: capability list.
IDENTITY_READONLY: dict[str, Any] = {
    **IDENTITY_ADMIN,
    "schluessel": {"name": "On the wall", "nur_lesen": True},
    "darf": ["lesen", "verwalten"],
}

#: An ordinary account: may ask for things, may not see the house.
IDENTITY_USER: dict[str, Any] = {
    "version": "0.30.0",
    "konto": {
        "id": 7,
        "username": "gast",
        "name": "Gast",
        "role": "user",
        "betreiber": False,
    },
    "schluessel": {"name": "Phone", "nur_lesen": False},
    "darf": ["lesen", "anfragen"],
}

TILE: dict[str, Any] = {
    "version": "0.30.0",
    "befunde": {"fehler": 1, "warnung": 2, "hinweis": 3, "dringendste": ["dienst.weg"]},
    "anfragen": {"wartend": 4, "laufend": 2, "fehlgeschlagen_7d": 1},
    "bibliothek": {
        "filme": 812,
        "serien": 94,
        "belegt_bytes": 12_000_000_000_000,
        "frei_bytes": 3_000_000_000_000,
    },
    "instanzen": [{"name": "Radarr", "erreichbar": True, "probleme": 0}],
    "tickets_offen": 2,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Without this, Home Assistant does not look in custom_components at all."""
    yield


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Nexview (Admin)",
        unique_id=f"{URL}::1",
        data={CONF_URL: URL, CONF_KEY: KEY, CONF_WEBHOOK_ID: WEBHOOK_ID},
    )


@pytest.fixture
def nexview(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """A Nexview that answers everything the happy path needs."""
    aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_ADMIN)
    aioclient_mock.get(f"{URL}/api/v1/dashboard", json=TILE)
    aioclient_mock.get(
        f"{URL}/api/v1/admin/requests/pending/count", json={"pending": 4}
    )
    aioclient_mock.get(f"{URL}/api/settings/channels/webhook/targets", json=[])
    return aioclient_mock


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
