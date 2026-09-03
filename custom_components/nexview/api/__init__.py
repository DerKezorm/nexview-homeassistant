"""The Nexview client - the half of this repository that knows no Home Assistant.

Import from here rather than from the modules underneath, so that lifting this
package out into ``python-nexview`` on PyPI later changes one import line.
"""

from .client import KEY_PREFIX, MIN_VERSION, NexviewClient
from .exceptions import (
    NexviewAuthError,
    NexviewConnectionError,
    NexviewError,
    NexviewNotFoundError,
    NexviewTooOldError,
)
from .models import (
    CAP_ADMINISTER,
    CAP_CONFIGURE,
    CAP_DECIDE,
    CAP_READ,
    CAP_REQUEST,
    Account,
    Identity,
    Instance,
    KeyInfo,
    Snapshot,
    Tile,
)

__all__ = [
    "CAP_ADMINISTER",
    "CAP_CONFIGURE",
    "CAP_DECIDE",
    "CAP_READ",
    "CAP_REQUEST",
    "KEY_PREFIX",
    "MIN_VERSION",
    "Account",
    "Identity",
    "Instance",
    "KeyInfo",
    "NexviewAuthError",
    "NexviewClient",
    "NexviewConnectionError",
    "NexviewError",
    "NexviewNotFoundError",
    "NexviewTooOldError",
    "Snapshot",
    "Tile",
]
