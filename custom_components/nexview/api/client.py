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
from .models import AccountUsage, Identity, Instance, Release, Tile, Version

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
                    return list(answer[key])
            return []
        return list(answer or [])

    async def instances(self) -> list[Instance]:
        """Every Radarr and Sonarr behind Nexview, with version and problems.

        Two calls because Nexview keeps them apart: one knows whether an
        instance answers and which version it runs, the other what it is
        complaining about. Neither is promised, and a guard in Nexview says so
        when either changes.
        """
        connections = await self._call("GET", "/api/settings/instanzen/verbindung")
        try:
            health = await self._call("GET", "/api/settings/instanzen/gesundheit")
        except NexviewError:
            # Problems are the optional half. Without them an instance still
            # has a name and a state, and that is most of the value.
            health = {}

        by_key = {
            str(h.get("kennung")): h for h in (health or {}).get("instanzen") or ()
        }
        return [
            Instance.from_detail(c, by_key.get(str(c.get("kennung"))))
            for c in (connections or {}).get("instanzen") or ()
        ]

    async def accounts(self) -> list[AccountUsage]:
        """What each account has used of its allowances.

        ⚠️ **From the statistics, not from the user list.** Both know the
        figures, but the user list also carries mail addresses, linked media
        server accounts and avatar paths, and the safest way not to pass those
        on is not to fetch them.
        """
        answer = await self._call("GET", "/api/admin/stats")
        return [AccountUsage.from_json(u) for u in (answer or {}).get("users") or ()]

    async def releases(self) -> list[Release]:
        """What is coming out, from Nexview's calendar."""
        answer = await self._call("GET", "/api/calendar")
        out: list[Release] = []
        for day in (answer or {}).get("days") or ():
            for entry in day.get("entries") or ():
                out.append(Release.from_json({**entry, "date": day.get("date")}))
        return out

    async def version(self) -> Version:
        """Installed version, and whether a newer one exists."""
        return Version.from_json(await self._call("GET", "/api/v1/about"))

    # --- Answering questions ----------------------------------------------
    #
    # These feed actions that return data. Lists belong here and never in an
    # entity attribute - Home Assistant is retiring that habit, and a list
    # that grows without bound was never a good state anyway.

    async def search(self, media_type: str, query: str) -> list[dict[str, Any]]:
        answer = await self._call(
            "GET", f"/api/v1/search/{media_type}", params={"query": query}
        )
        if isinstance(answer, dict):
            treffer = answer.get("results") or answer.get("items") or []
            return list(treffer)
        return list(answer or [])

    async def requests(self, status: str | None = None) -> list[dict[str, Any]]:
        """Requests, optionally filtered by status.

        ⚠️ **Deliberately narrowed on the way out.** Nexview answers with
        avatars, ratings, storage figures of whoever asked, and the name of a
        child a request was made for. An action's response ends up in
        automations and traces, so it carries the few fields somebody actually
        automates on and drops the rest.
        """
        raw = await self._call(
            "GET", "/api/admin/requests", params={"status": status} if status else None
        )
        rows = raw if isinstance(raw, list) else (raw or {}).get("items") or []
        return [
            {
                "id": r.get("id"),
                "title": r.get("title"),
                "media_type": r.get("media_type"),
                "status": r.get("status"),
                "tmdb_id": r.get("tmdb_id"),
                "season": r.get("season"),
                "requested_at": r.get("requested_at"),
                "requested_by": r.get("display_name") or r.get("username"),
                "progress": r.get("laedt_fortschritt"),
                "downloading_since": r.get("laedt_seit"),
            }
            for r in rows
        ]

    async def active_downloads(self) -> list[dict[str, Any]]:
        """What is being fetched right now, with progress.

        A count of these is a sensor; the list itself is not. One entity per
        download would come and go all day and leave the registry full of
        things that no longer exist.
        """
        laufend = await self.requests()
        return [
            r
            for r in laufend
            if r.get("status") in ("approved", "searching", "downloading")
        ]

    # --- Operator errands -------------------------------------------------

    async def test_connection(self, service: str) -> dict[str, Any]:
        """Ask Nexview to talk to one instance now.

        ``service`` is one of ``radarr``, ``sonarr``, ``radarr_uhd``,
        ``sonarr_uhd``. The empty body is required and means "use what is
        saved" - the endpoint also serves the settings screen, where somebody
        tests credentials before storing them.
        """
        antwort = await self._call("POST", f"/api/settings/test/{service}", json={})
        return dict(antwort or {})

    async def storage_sync(self) -> None:
        await self._call("POST", "/api/storage/abgleich")

    async def check_update(self) -> None:
        await self._call("POST", "/api/about/check")

    async def acknowledge_findings(self) -> None:
        await self._call("POST", "/api/admin/dashboard/gesehen")

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
        antwort = await self._call(
            "POST",
            "/api/settings/channels/webhook/targets",
            json={"name": name, "url": url, "token": "", "language": "en"},
        )
        return dict(antwort or {})

    async def webhook_events(self, target_id: int, events: dict[str, str]) -> None:
        await self._call(
            "PUT",
            f"/api/settings/channels/webhook/targets/{target_id}/events",
            json={"events": events},
        )

    async def webhook_delete(self, target_id: int) -> None:
        await self._call("DELETE", f"/api/settings/channels/webhook/targets/{target_id}")
