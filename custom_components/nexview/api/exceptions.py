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


class NexviewNotFoundError(NexviewError):
    """Nexview answered 404.

    ⚠️ **Two very different things wear the same status code.** Either the
    address does not exist - then this Nexview is older than the integration -
    or the thing named in it does not, such as a request number that was
    already decided. The caller knows which of the two it asked for; this
    exception only carries the path so it can say.
    """

    def __init__(self, path: str) -> None:
        super().__init__(f"Nexview has nothing at {path}")
        self.path = path


class NexviewTooOldError(NexviewError):
    """This Nexview is older than the integration needs.

    Raised only where a missing endpoint cannot be worked around. Anything
    that merely limits what can be shown is handled by capabilities instead,
    so an older installation still gets what it can give.
    """
