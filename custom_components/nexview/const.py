"""Names that more than one module needs.

⚠️ **Anything written into a config entry is forever.** Renaming a key here
means writing a migration, because entries created by earlier versions still
carry the old name. That is why they are short and plain.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "nexview"

#: What the user typed in the dialog. Connection data belongs in ``entry.data``;
#: everything adjustable belongs in ``entry.options``.
CONF_URL: Final = "url"
CONF_KEY: Final = "api_key"
CONF_WEBHOOK_ID: Final = "webhook_id"

#: Which Nexview accounts get entities of their own. Lives in ``entry.options``
#: because it is adjustable, not part of the connection.
#:
#: ⚠️ **Empty means none, not all.** A house with thirty accounts would
#: otherwise get a hundred and twenty entities from one click, and every new
#: Nexview account would quietly add four more.
CONF_ACCOUNTS: Final = "accounts"

#: Soll Nexview dieses Home Assistant anrufen?
#:
#: ⚠️ **An per Vorgabe, und im Einrichtungsassistenten steht er nicht.** Wer
#: die Integration einrichtet, hat noch keine Vorstellung davon, was ein
#: Rueckkanal ist; eine Frage, die man nicht beantworten kann, macht den
#: Einstieg schlechter. Gebraucht wird der Haken genau dann, wenn Nexview
#: dieses Home Assistant nicht erreichen kann und jemand die Reparaturmeldung
#: loswerden will, ohne dass sie bei jedem Neustart wiederkommt.
CONF_PUSH: Final = "push"

#: How this Home Assistant appears in Nexview, next to the key that registered
#: it. Recognisable on sight, because a person will eventually have to decide
#: which of several entries may be disconnected.
TARGET_PREFIX: Final = "Home Assistant"

#: How often we ask when nothing pushes to us. Half a minute is what makes a
#: dashboard feel live without being noticeable in Nexview's log.
POLL_IDLE: Final = timedelta(seconds=30)

#: And how often once the way back works. Not zero on purpose: a lost call
#: would otherwise leave Home Assistant sitting on a wrong number until the
#: next event happens to arrive.
POLL_PUSHED: Final = timedelta(minutes=5)


#: Nexview's notification types, sorted into the three event entities. The keys
#: are what arrives in the ``event`` field of the payload.
#:
#: ⚠️ **Unknown types are not dropped.** Nexview will grow new ones, and an
#: integration that silently ignores them looks broken to whoever is waiting
#: for the automation to fire. What is not listed here lands on the operations
#: entity as ``other``.
EVENT_REQUESTS: Final = "requests"
EVENT_STORAGE: Final = "storage"
EVENT_OPERATIONS: Final = "operations"

EVENT_ROUTING: Final[dict[str, tuple[str, str]]] = {
    "request_pending": (EVENT_REQUESTS, "pending"),
    "approved": (EVENT_REQUESTS, "approved"),
    "rejected": (EVENT_REQUESTS, "rejected"),
    "cancelled": (EVENT_REQUESTS, "cancelled"),
    "request_deferred": (EVENT_REQUESTS, "deferred"),
    "download_complete": (EVENT_REQUESTS, "downloaded"),
    "storage_release_requested": (EVENT_STORAGE, "release_requested"),
    "storage_released": (EVENT_STORAGE, "released"),
    "storage_kept": (EVENT_STORAGE, "kept"),
    "storage_deleted": (EVENT_STORAGE, "deleted"),
    "storage_grew": (EVENT_STORAGE, "grew"),
    "instance_health": (EVENT_OPERATIONS, "instance_health"),
    "ticket_new": (EVENT_OPERATIONS, "ticket"),
    "feedback": (EVENT_OPERATIONS, "feedback"),
    "feedback_poor": (EVENT_OPERATIONS, "feedback"),
    "user_imported": (EVENT_OPERATIONS, "user_imported"),
}

#: The types each event entity declares. Home Assistant refuses to fire a type
#: an entity did not declare, so ``other`` has to be in here for the unknown
#: ones to have somewhere to land.
EVENT_TYPES: Final[dict[str, list[str]]] = {
    EVENT_REQUESTS: [
        "pending",
        "approved",
        "rejected",
        "cancelled",
        "deferred",
        "downloaded",
    ],
    EVENT_STORAGE: ["release_requested", "released", "kept", "deleted", "grew"],
    EVENT_OPERATIONS: [
        "instance_health",
        "ticket",
        "feedback",
        "user_imported",
        "other",
    ],
}

# --- Actions ---------------------------------------------------------------

SERVICE_APPROVE: Final = "approve_request"
SERVICE_REJECT: Final = "reject_request"
SERVICE_DEFER: Final = "defer_request"
SERVICE_CANCEL: Final = "cancel_request"

#: Actions that answer instead of doing something. Kept apart because Home
#: Assistant registers them differently, and because these are the ones that
#: may be called without changing anything.
SERVICE_SEARCH: Final = "search"
SERVICE_LIST_REQUESTS: Final = "list_requests"
SERVICE_ACTIVE_DOWNLOADS: Final = "active_downloads"
SERVICE_GET_QUOTA: Final = "get_quota"
SERVICE_NOW_PLAYING: Final = "now_playing"

ATTR_REQUEST_ID: Final = "request_id"
ATTR_QUERY: Final = "query"
ATTR_MEDIA_TYPE: Final = "media_type"
ATTR_STATUS: Final = "status"
ATTR_ACCOUNT: Final = "account_id"
ATTR_REASON: Final = "reason"
ATTR_CONFIG_ENTRY: Final = "config_entry_id"
