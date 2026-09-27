"""What can go wrong when talking to Nexview.

Kept apart from the integration on purpose: Home Assistant maps each of these
onto its own behaviour (retry, re-auth, give up), and that mapping is the
integration's job, not this package's.
"""

from __future__ import annotations


class NexviewError(Exception):
    """Base for everything this package raises."""


class NexviewConnectionError(NexviewError):
    """Nexview did not answer, or not in time.

    Transient by assumption. The caller should try again later rather than
    tear anything down.
    """


class NexviewAuthError(NexviewError):
    """The key was rejected, or it may not do this.

    Covers both 401 and 403 deliberately. From the outside they are the same
    problem - this key cannot do what was asked - and the cure is the same:
    a human has to look at the key.
    """


class NexviewResponseError(NexviewError):
    """Nexview answered, and the answer was an error.

    ⚠️ **The code, never the sentence.** Since 1.0 Nexview answers a refusal
    with ``{"detail": {"code": ..., "message": ...}}``. The code is meant for
    machines and stays the same between releases; the message is a German
    fallback for readers without an interface. Only the code and the service
    it names are kept here, so there is nothing a caller could put on a screen
    by mistake. The caller translates the code itself, and whatever it does not
    know it shows as the code.
    """

    def __init__(
        self,
        method: str,
        path: str,
        status: int,
        code: str | None = None,
        service: str | None = None,
    ) -> None:
        wie = f"HTTP {status}, {code}" if code else f"HTTP {status}"
        super().__init__(f"Nexview refused {method} {path} ({wie})")
        self.path = path
        self.status = status
        self.code = code
        self.service = service


class NexviewNotFoundError(NexviewResponseError):
    """Nexview answered 404.

    ⚠️ **Two very different things wear the same status code.** Either the
    address does not exist - then this Nexview is older than the integration -
    or the thing named in it does not, such as a request number that was
    already decided. The caller knows which of the two it asked for; this
    exception only carries the path so it can say.
    """

    def __init__(self, path: str, code: str | None = None, method: str = "GET") -> None:
        super().__init__(method, path, 404, code)


class NexviewConflictError(NexviewResponseError):
    """Nexview answered 409.

    Nexview 1.0 says so for an address that belongs to the other way of
    getting media: with nexcrate instead of Radarr and Sonarr, the Radarr and
    Sonarr tools answer ``409 not_in_this_mode``. It also says so for a
    decision that does not fit the request any more, with a code that names
    why (``request_not_pending``, ``defer_nothing_to_wait_for``). The caller
    decides whether it can do without.
    """

    def __init__(
        self,
        path: str,
        code: str | None = None,
        service: str | None = None,
        method: str = "GET",
    ) -> None:
        super().__init__(method, path, 409, code, service)


class NexviewTooOldError(NexviewError):
    """This Nexview is older than the integration needs.

    Raised only where a missing endpoint cannot be worked around. Anything
    that merely limits what can be shown is handled by capabilities instead,
    so an older installation still gets what it can give.
    """
