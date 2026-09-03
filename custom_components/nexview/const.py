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

#: How this Home Assistant appears in Nexview's list of notification targets.
#: Recognisable on sight, because a person will eventually have to decide which
#: of several entries may be revoked.
TARGET_PREFIX: Final = "Home Assistant"

#: How often we ask when nothing pushes to us. Half a minute is what makes a
#: dashboard feel live without being noticeable in Nexview's log.
POLL_IDLE: Final = timedelta(seconds=30)

#: And how often once the way back works. Not zero on purpose: a lost call
#: would otherwise leave Home Assistant sitting on a wrong number until the
#: next event happens to arrive.
POLL_PUSHED: Final = timedelta(minutes=5)

#: Which of Nexview's notification groups we subscribe to, and at which
#: urgency. Nexview stores the urgency per hook; for us it only decides how
#: prominent its own delivery is, so everything that needs a person gets
#: ``high`` and the rest stays ``normal``.
WEBHOOK_EVENTS: Final[dict[str, str]] = {
    "request_pending": "high",
    "request_decided": "normal",
    "request_cancelled": "normal",
    "download_complete": "normal",
    "ticket_new": "normal",
    "feedback": "normal",
    "user_imported": "normal",
    "storage_release": "normal",
    "instance_health": "high",
}

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

ATTR_REQUEST_ID: Final = "request_id"
ATTR_REASON: Final = "reason"
ATTR_CONFIG_ENTRY: Final = "config_entry_id"
