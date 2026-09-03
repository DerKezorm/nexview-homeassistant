"""What to hand somebody who is trying to work out why this is not working.

⚠️ **Diagnostics get attached to public issue reports.** Somebody with a
problem downloads this file and drops it into a GitHub issue, where it stays
forever. So this answers the questions that actually help - what the key may
do, whether the way back stands, how many of everything there is - and names
nobody.

Specifically not in here: the access key, the address of the installation, the
webhook id (which is a secret in its own right - anybody who has it can post
events), account names, and the titles of what anybody requested.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_KEY, CONF_URL, CONF_WEBHOOK_ID
from .coordinator import NexviewConfigEntry

#: Redacted rather than dropped, so the shape of the entry stays visible and
#: it is obvious that something was removed rather than never set.
TO_REDACT = {CONF_KEY, CONF_URL, CONF_WEBHOOK_ID}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NexviewConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
            "version": entry.version,
        },
        "connection": {
            "nexview_version": data.identity.version,
            "reachable": coordinator.last_update_success,
            "pushing": coordinator.pushing,
            "poll_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
        },
        "key": {
            # ⚠️ The capabilities, not the account. Which of the five a key
            # has is the single most useful thing when entities are missing,
            # and it says nothing about who owns it.
            "may": sorted(data.identity.capabilities),
            "role": data.identity.account.role,
            "is_operator": data.identity.account.operator,
            "read_only": data.identity.key.read_only if data.identity.key else None,
        },
        "what_was_read": {
            # Whether each optional call came back, without its contents. This
            # is what separates "no rights" from "Nexview did not answer".
            "tile": data.tile is not None,
            "pending_count": data.pending_count is not None,
            "version": data.version is not None,
            "instances": len(data.instances),
            "accounts_selected": len(data.accounts),
        },
        "instances": [
            {
                # The key, not the name: names are chosen by the operator and
                # can say anything, including somebody's name.
                "key": instance.key,
                "reachable": instance.reachable,
                "problems": instance.problems,
                "version": instance.version,
            }
            for instance in data.instances.values()
        ],
        "tile": (
            {
                "findings": {
                    "error": data.tile.findings_error,
                    "warning": data.tile.findings_warning,
                    "hint": data.tile.findings_hint,
                    # Stable identifiers such as dienst.nicht_erreichbar. No
                    # free text, so nothing in here was written by a person.
                    "worst": list(data.tile.findings_worst),
                },
                "requests": {
                    "pending": data.tile.pending,
                    "processing": data.tile.processing,
                    "failed_7d": data.tile.failed_7d,
                },
                "library": {
                    "movies": data.tile.movies,
                    "series": data.tile.series,
                },
            }
            if data.tile
            else None
        ),
    }
