"""The two lines about Nexview on Home Assistant's system health page.

Not a substitute for the diagnostics download - this is the glance somebody
takes when something feels off, before they know what they are looking for.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .coordinator import NexviewConfigEntry


@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    register.async_register_info(system_health_info)


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    entries: list[NexviewConfigEntry] = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        return {"connected": 0}

    # ⚠️ Counted, not listed. This page is a glance, and one line per
    # installation would push everything else off the screen in a house that
    # connects Nexview twice.
    pushing = sum(1 for e in entries if e.runtime_data.pushing)
    answering = sum(1 for e in entries if e.runtime_data.last_update_success)

    return {
        "connected": len(entries),
        "answering": answering,
        # The interesting one: everything works without the way back, just
        # slower and later, and this is where that shows.
        "receiving_events": pushing,
        "nexview_version": entries[0].runtime_data.data.identity.version,
    }
