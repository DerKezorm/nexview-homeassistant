"""Everything that talks to Nexview, and nothing that knows about Home Assistant.

⚠️ **Why this is a package of its own.** The Home Assistant core requires that
an integration's communication with its service lives in a separate library, so
that core maintainers never have to maintain it. Publishing to PyPI can wait;
the separation cannot, because doing it afterwards touches every file.

The rule that keeps it honest: nothing under ``api/`` may import from
``homeassistant``, and a test says so. The session is handed in from outside,
which is what the quality scale asks for anyway - one shared connection pool
instead of one per integration.
"""

from __future__ import annotations

import logging
from json import loads as json_loads
from typing import Any

import aiohttp
from yarl import URL

from .exceptions import (
    NexviewAuthError,
    NexviewConnectionError,
    NexviewError,
    NexviewNotFoundError,
    NexviewTooOldError,
)
from .models import Identity, Tile

_LOGGER = logging.getLogger(__name__)

#: Generous enough for a busy instance answering a dashboard call, short enough
#: that a dead server does not hold up a poll cycle.
TIMEOUT = aiohttp.ClientTimeout(total=15)

#: The prefix Nexview gives its personal access keys. Checked before anything is
#: sent, so a pasted password fails in the dialog instead of as a 401.
KEY_PREFIX = "nxv_"

#: Below this, ``GET /api/v1/me`` does not exist and there is no way to tell
#: what a key may do. Older installations are turned away in the config flow
#: with a sentence that says what to do about it.
MIN_VERSION = "0.30.0"


class NexviewClient:
    """One Nexview, one key."""

    def __init__(self, session: aiohttp.ClientSession, url: str, key: str) -> None:
        self._session = session
        self._url = URL(url.rstrip("/"))
        self._key = key

    @property
    def url(self) -> str:
        return str(self._url)

    async def _call(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """One request, with every failure turned into one of our own errors."""
        target = self._url.join(URL(path))
        try:
            async with self._session.request(
                method,
                target,
                json=json,
                params=params,
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=TIMEOUT,
            ) as response:
                if response.status in (401, 403):
                    # ⚠️ Both mean the same to us: a human has to look at the
                    # key. Home Assistant turns this into a re-auth flow.
                    raise NexviewAuthError(
                        f"Nexview refused the key for {method} {path}"
                        f" (HTTP {response.status})"
                    )
                if response.status == 404:
                    raise NexviewNotFoundError(path)
                response.raise_for_status()
                if response.status == 204:
                    return None
                # ⚠️ Read the body, do not trust a length header. With chunked
                # transfer there is no content length even though a body is on
                # its way, and Nexview sits behind whatever proxy the operator
                # happens to run.
                # (``json_loads`` rather than ``json.loads``: the keyword
                # argument below is called ``json``, matching aiohttp, and it
                # would shadow the module.)
                text = await response.text()
                return json_loads(text) if text.strip() else None
        except NexviewError:
            raise
        except aiohttp.ClientResponseError as err:
            raise NexviewError(f"Nexview answered HTTP {err.status} for {path}") from err
        except TimeoutError as err:
            raise NexviewConnectionError(
                f"Nexview did not answer in time ({path})"
            ) from err
        except aiohttp.ClientError as err:
            raise NexviewConnectionError(f"Nexview was not reachable: {err}") from err

    # --- What we are ------------------------------------------------------

    async def identity(self) -> Identity:
        """Who this key belongs to and what it may do.

        The first call of every setup and of every poll: what a key may do can
        change while Home Assistant runs - somebody marks it read only, an
        account loses its role - and the entities have to follow.

        ⚠️ **Age is decided by the answer, not by the version number.** An
        installation too old for this integration is one where this address
        does not exist; comparing version strings would mean parsing them, and
        being wrong about a release candidate or a fork.
        """
        try:
            raw = await self._call("GET", "/api/v1/me")
        except NexviewNotFoundError as err:
            # Here a 404 can only mean the address itself is missing - there is
            # no name in it that could be the thing that is gone.
            raise NexviewTooOldError(
                f"This Nexview has no /api/v1/me, so it is older than {MIN_VERSION}"
            ) from err
        return Identity.from_json(raw)

    # --- What is going on -------------------------------------------------

    async def tile(self) -> Tile:
        """The dashboard tile. Needs a key that may administer."""
        return Tile.from_json(await self._call("GET", "/api/v1/dashboard"))

    async def pending_count(self) -> int:
        """How many requests wait. Enough for a key that may only decide."""
        answer = await self._call("GET", "/api/v1/admin/requests/pending/count")
        return int((answer or {}).get("pending", 0))

    async def pending_requests(self) -> list[dict[str, Any]]:
        """The waiting requests themselves.

        ⚠️ **Not a promised address.** ``/api/admin/requests`` may change
        between Nexview releases; a guard in Nexview's own test suite says so
        out loud when it does. Worth it: without the list there is nothing to
        approve, only a number to look at.
        """
        answer = await self._call(
            "GET", "/api/admin/requests", params={"status": "pending"}
        )
        if isinstance(answer, dict):
            for key in ("items", "requests", "anfragen"):
                if isinstance(answer.get(key), list):
                    return answer[key]
            return []
        return answer or []

    # --- Deciding ---------------------------------------------------------

    async def approve(self, request_id: int) -> None:
        await self._call("POST", f"/api/admin/requests/{request_id}/approve")

    async def reject(self, request_id: int, reason: str | None = None) -> None:
        await self._call(
            "POST",
            f"/api/admin/requests/{request_id}/reject",
            json={"grund": reason} if reason else None,
        )

    async def defer(self, request_id: int) -> None:
        await self._call("POST", f"/api/admin/requests/{request_id}/defer")

    async def cancel(self, request_id: int) -> None:
        await self._call("POST", f"/api/admin/requests/{request_id}/cancel")

    # --- The way back -----------------------------------------------------
    #
    # Nexview pushes to a plain webhook, and its own source names Home
    # Assistant as the first case it was built for. Setting one up takes four
    # steps, and all four are ours to take - nobody should have to copy a code
    # between two browser tabs.

    async def webhook_targets(self) -> list[dict[str, Any]]:
        return await self._call("GET", "/api/settings/channels/webhook/targets") or []

    async def webhook_test(self, name: str, url: str) -> None:
        """Ask Nexview to send its test message - which is how we learn the code."""
        answer = await self._call(
            "POST",
            "/api/settings/channels/webhook/test",
            # English, because this message is aimed at us, not at a reader.
            json={"name": name, "url": url, "token": "", "language": "en"},
        )
        if not (answer or {}).get("ok"):
            raise NexviewError(
                (answer or {}).get("message") or "Nexview could not reach us"
            )

    async def webhook_confirm(self, code: str) -> None:
        answer = await self._call(
            "POST", "/api/settings/channels/webhook/confirm", json={"code": code}
        )
        if not (answer or {}).get("ok"):
            raise NexviewError(
                (answer or {}).get("message") or "Nexview rejected the code"
            )

    async def webhook_save(self, name: str, url: str) -> dict[str, Any]:
        return await self._call(
            "POST",
            "/api/settings/channels/webhook/targets",
            json={"name": name, "url": url, "token": "", "language": "en"},
        )

    async def webhook_events(self, target_id: int, events: dict[str, str]) -> None:
        await self._call(
            "PUT",
            f"/api/settings/channels/webhook/targets/{target_id}/events",
            json={"events": events},
        )

    async def webhook_delete(self, target_id: int) -> None:
        await self._call("DELETE", f"/api/settings/channels/webhook/targets/{target_id}")
