"""Nexview in Home Assistant.

What this does at setup, in order: check the key, find out what it may do,
register the webhook that Nexview will call, tell Nexview about it, and only
then create entities - as many as the key is actually allowed to fill.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.typing import ConfigType

from .api import (
    CAP_DECIDE,
    AccountUsage,
    NexviewAuthError,
    NexviewClient,
    NexviewConnectionError,
    NexviewError,
    NexviewNotFoundError,
)
from .const import (
    ATTR_ACCOUNT,
    ATTR_CONFIG_ENTRY,
    ATTR_MEDIA_TYPE,
    ATTR_QUERY,
    ATTR_REASON,
    ATTR_REQUEST_ID,
    ATTR_STATUS,
    CONF_KEY,
    CONF_URL,
    DOMAIN,
    SERVICE_ACTIVE_DOWNLOADS,
    SERVICE_APPROVE,
    SERVICE_CANCEL,
    SERVICE_DEFER,
    SERVICE_GET_QUOTA,
    SERVICE_LIST_REQUESTS,
    SERVICE_NOW_PLAYING,
    SERVICE_REJECT,
    SERVICE_SEARCH,
)
from .coordinator import NexviewConfigEntry, NexviewCoordinator
from .webhook import NexviewWebhook

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.EVENT,
    Platform.SENSOR,
    Platform.UPDATE,
]

_DECISION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_REQUEST_ID): cv.positive_int,
        vol.Optional(ATTR_CONFIG_ENTRY): cv.string,
    }
)

_REJECT_SCHEMA = _DECISION_SCHEMA.extend({vol.Optional(ATTR_REASON): cv.string})

_ENTRY_ONLY_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY): cv.string})

_SEARCH_SCHEMA = _ENTRY_ONLY_SCHEMA.extend(
    {
        vol.Required(ATTR_QUERY): cv.string,
        vol.Optional(ATTR_MEDIA_TYPE, default="movie"): vol.In(["movie", "tv"]),
    }
)

_LIST_SCHEMA = _ENTRY_ONLY_SCHEMA.extend({vol.Optional(ATTR_STATUS): cv.string})

_QUOTA_SCHEMA = _ENTRY_ONLY_SCHEMA.extend({vol.Optional(ATTR_ACCOUNT): cv.positive_int})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions.

    ⚠️ **Here and not in ``async_setup_entry``.** Actions registered per entry
    exist only while that entry is loaded, and Home Assistant can then no
    longer check automations that use them - an automation referring to an
    action that momentarily does not exist reads as broken. The handler checks
    for itself whether the entry is loaded and says so plainly when it is not.
    """
    await _async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NexviewConfigEntry) -> bool:
    client = NexviewClient(
        async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_KEY]
    )
    coordinator = NexviewCoordinator(hass, entry, client)

    # ⚠️ First fetch before anything else exists. A key that no longer works
    # has to lead into re-auth here, not into a dozen unavailable entities.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    hook = NexviewWebhook(hass, entry)
    hook.register()
    entry.async_on_unload(hook.unregister)

    pushing = await hook.async_ensure_target()
    coordinator.set_pushing(pushing)
    _async_report_push(hass, entry, pushing=pushing, url=hook.url)

    # ⚠️ **Nexview itself is registered here, not as a side effect.** The
    # instances and accounts hang off it by device id, and an id only exists
    # once the device does. Letting the first entity create it would make the
    # tree depend on which platform happened to load first.
    devices = dr.async_get(hass)
    main = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        entry_type=dr.DeviceEntryType.SERVICE,
        manufacturer="nexapps",
        name=entry.title,
        configuration_url=client.url,
        sw_version=coordinator.data.identity.version,
    )
    coordinator.main_device_id = main.id

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NexviewConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: NexviewConfigEntry, device: DeviceEntry
) -> bool:
    """May this device be deleted by hand?

    ⚠️ **Only what Nexview no longer has.** An instance or an account that
    disappeared for a moment - somebody is editing settings over there - comes
    back with its history intact, so nothing is removed automatically. But a
    Sonarr that was taken out for good, or an account that was deleted, would
    otherwise sit in the list forever with no way to get rid of it. This is
    that way, and it refuses while the thing still exists.

    Nexview itself is never removable: deleting the entry is how that is done.
    """
    data = entry.runtime_data.data
    for domain, identifier in device.identifiers:
        if domain != DOMAIN:
            continue
        if identifier == entry.entry_id:
            return False
        rest = identifier.removeprefix(f"{entry.entry_id}_")
        if rest.startswith("account"):
            try:
                user_id = int(rest.removeprefix("account"))
            except ValueError:
                return True
            return user_id not in data.accounts
        return rest not in data.instances
    return True


def _async_report_push(
    hass: HomeAssistant, entry: ConfigEntry, *, pushing: bool, url: str
) -> None:
    """Say out loud when the way back is missing.

    ⚠️ **Because silence is the worse failure.** Everything still works
    without the push - Home Assistant simply asks more often - but events
    arrive late or not at all, and nothing on screen explains why. The Seerr
    integration has exactly this gap: its event entity stays mute and its
    quality file claims there is no case for a repair issue. There is.
    """
    issue_id = f"push_missing_{entry.entry_id}"
    if pushing:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="push_missing",
        translation_placeholders={"url": url, "name": entry.title},
    )


async def _async_register_services(hass: HomeAssistant) -> None:
    async def _entry_for(
        call: ServiceCall, *, needs_decide: bool = True
    ) -> NexviewConfigEntry:
        """Find the entry this call means, and refuse clearly if there is none.

        ``needs_decide`` is off for the actions that only answer: reading what
        is waiting has nothing to do with being allowed to decide it.
        """
        entries: list[NexviewConfigEntry] = [
            entry
            for entry in hass.config_entries.async_loaded_entries(DOMAIN)
            if ATTR_CONFIG_ENTRY not in call.data
            or entry.entry_id == call.data[ATTR_CONFIG_ENTRY]
        ]
        if not entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_entry"
            )
        if len(entries) > 1:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="ambiguous_entry"
            )
        entry = entries[0]
        if needs_decide and not entry.runtime_data.data.identity.may(CAP_DECIDE):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="may_not_decide",
                translation_placeholders={"name": entry.title},
            )
        return entry

    async def _run(call: ServiceCall, what: str) -> None:
        entry = await _entry_for(call)
        client = entry.runtime_data.client
        request_id = call.data[ATTR_REQUEST_ID]
        try:
            if what == SERVICE_APPROVE:
                await client.approve(request_id)
            elif what == SERVICE_REJECT:
                await client.reject(request_id, call.data.get(ATTR_REASON))
            elif what == SERVICE_DEFER:
                await client.defer(request_id)
            else:
                await client.cancel(request_id)
        except NexviewAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except NexviewNotFoundError as err:
            # ⚠️ Not a failure of the integration, and it must not read like
            # one. Nexview answers 404 for a request number that was already
            # decided or never existed, and "Nexview has nothing at
            # /api/admin/requests/42/approve" sends people looking for a
            # broken address instead of a wrong number.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_request",
                translation_placeholders={"request_id": str(request_id)},
            ) from err
        except NexviewConnectionError as err:
            raise _failed(err, "unreachable") from err
        except NexviewError as err:
            raise _failed(err, "request_failed") from err

        # The number on screen should not lag behind what was just decided.
        await entry.runtime_data.async_request_refresh()

    for service, schema in (
        (SERVICE_APPROVE, _DECISION_SCHEMA),
        (SERVICE_REJECT, _REJECT_SCHEMA),
        (SERVICE_DEFER, _DECISION_SCHEMA),
        (SERVICE_CANCEL, _DECISION_SCHEMA),
    ):

        async def handler(call: ServiceCall, _service: str = service) -> None:
            await _run(call, _service)

        hass.services.async_register(DOMAIN, service, handler, schema=schema)

    # --- The ones that answer ---------------------------------------------
    #
    # ⚠️ **This is where lists belong.** Home Assistant is retiring long lists
    # in entity attributes - the ones on Sonarr expire with 2026.9 - and this
    # is the replacement: ask, get an answer, use it in the automation that
    # asked. An entity would have to hold the whole list all day for the one
    # minute a year somebody looks at it.

    def _quota_json(account: AccountUsage) -> dict[str, Any]:
        return {
            "account_id": account.user_id,
            "name": account.name,
            "movies": {
                "used": account.movies.used,
                "limit": account.movies.limit,
                "remaining": account.movies.remaining,
            },
            "series": {
                "used": account.series.used,
                "limit": account.series.limit,
                "remaining": account.series.remaining,
            },
            "storage_bytes": {
                "used": account.storage.used,
                "limit": account.storage.limit,
                "remaining": account.storage.remaining,
            },
        }

    async def _answer(call: ServiceCall, what: str) -> ServiceResponse:
        entry = await _entry_for(call, needs_decide=False)
        client = entry.runtime_data.client
        try:
            antwort: dict[str, Any]
            if what == SERVICE_SEARCH:
                antwort = {
                    "results": await client.search(
                        call.data[ATTR_MEDIA_TYPE], call.data[ATTR_QUERY]
                    )
                }
            elif what == SERVICE_LIST_REQUESTS:
                antwort = {"requests": await client.requests(call.data.get(ATTR_STATUS))}
            elif what == SERVICE_ACTIVE_DOWNLOADS:
                antwort = {"downloads": await client.active_downloads()}
            elif what == SERVICE_NOW_PLAYING:
                # ⚠️ Here and not as an attribute. This carries who is
                # watching what on which device, and that is an answer to a
                # question asked now, not something to keep for years.
                antwort = {"playing": await client.now_playing()}
            else:
                wanted = call.data.get(ATTR_ACCOUNT)
                antwort = {
                    "accounts": [
                        _quota_json(a)
                        for a in await client.accounts()
                        if wanted is None or a.user_id == wanted
                    ]
                }
            # Everything in here came out of Nexview as JSON and goes back out
            # as JSON; the type checker cannot see that through dict[str, Any].
            return cast(ServiceResponse, antwort)
        except NexviewAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except NexviewConnectionError as err:
            raise _failed(err, "unreachable") from err
        except NexviewError as err:
            raise _failed(err, "request_failed") from err

    for service, schema in (
        (SERVICE_SEARCH, _SEARCH_SCHEMA),
        (SERVICE_LIST_REQUESTS, _LIST_SCHEMA),
        (SERVICE_ACTIVE_DOWNLOADS, _ENTRY_ONLY_SCHEMA),
        (SERVICE_GET_QUOTA, _QUOTA_SCHEMA),
        (SERVICE_NOW_PLAYING, _ENTRY_ONLY_SCHEMA),
    ):

        async def answering(
            call: ServiceCall, _service: str = service
        ) -> ServiceResponse:
            return await _answer(call, _service)

        hass.services.async_register(
            DOMAIN,
            service,
            answering,
            schema=schema,
            supports_response=SupportsResponse.ONLY,
        )


def _failed(err: Exception, key: str) -> HomeAssistantError:
    """A Nexview failure, phrased for whoever reads the automation trace.

    ⚠️ Translated, not formatted here. Whoever runs this in German should not
    have to read an English sentence to find out that a request did not go
    through.
    """
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={"error": str(err)},
    )
