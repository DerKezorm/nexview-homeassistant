"""The shapes Nexview answers with, as plain objects.

⚠️ Only the fields the integration actually uses. Copying an API into
dataclasses field for field creates a second place to maintain and a lot of
attributes nobody reads.

Every ``from_json`` is written to survive a field that is not there yet: an
older Nexview may answer without it, and that is a reason to show less, never
a reason to fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: What a key is allowed to do. Nexview returns these as stable identifiers
#: in ``GET /api/v1/me``; they are German words because that is what the API
#: promises, and translating them here would only hide where they came from.
CAP_READ = "lesen"
CAP_REQUEST = "anfragen"
CAP_DECIDE = "entscheiden"
CAP_ADMINISTER = "verwalten"
CAP_CONFIGURE = "einrichten"


@dataclass(frozen=True, slots=True)
class Account:
    id: int
    username: str
    name: str
    role: str
    operator: bool

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Account:
        return cls(
            id=int(raw.get("id", 0)),
            username=str(raw.get("username", "")),
            name=str(raw.get("name") or raw.get("username", "")),
            role=str(raw.get("role", "user")),
            operator=bool(raw.get("betreiber", False)),
        )


@dataclass(frozen=True, slots=True)
class KeyInfo:
    name: str
    read_only: bool

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> KeyInfo:
        return cls(
            name=str(raw.get("name", "")),
            read_only=bool(raw.get("nur_lesen", False)),
        )


@dataclass(frozen=True, slots=True)
class Identity:
    """The answer to ``GET /api/v1/me`` - who we are and what we may do."""

    version: str
    account: Account
    #: ``None`` when a browser session was used instead of an access key.
    key: KeyInfo | None
    capabilities: frozenset[str]

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Identity:
        key = raw.get("schluessel")
        return cls(
            version=str(raw.get("version", "")),
            account=Account.from_json(raw.get("konto") or {}),
            key=KeyInfo.from_json(key) if key else None,
            capabilities=frozenset(raw.get("darf") or []),
        )

    def may(self, capability: str) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True, slots=True)
class Instance:
    """One Radarr or Sonarr behind Nexview."""

    name: str
    reachable: bool
    problems: int

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Instance:
        return cls(
            name=str(raw.get("name", "")),
            reachable=bool(raw.get("erreichbar", False)),
            problems=int(raw.get("probleme", 0) or 0),
        )


@dataclass(frozen=True, slots=True)
class Tile:
    """``GET /api/v1/dashboard`` - nearly every sensor value in one call."""

    version: str
    findings_error: int
    findings_warning: int
    findings_hint: int
    #: Up to three stable keys such as ``dienst.nicht_erreichbar``.
    findings_worst: tuple[str, ...]
    pending: int
    processing: int
    failed_7d: int
    movies: int
    series: int
    used_bytes: int
    free_bytes: int
    open_tickets: int
    instances: tuple[Instance, ...]

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Tile:
        findings = raw.get("befunde") or {}
        requests = raw.get("anfragen") or {}
        library = raw.get("bibliothek") or {}
        return cls(
            version=str(raw.get("version", "")),
            findings_error=int(findings.get("fehler", 0) or 0),
            findings_warning=int(findings.get("warnung", 0) or 0),
            findings_hint=int(findings.get("hinweis", 0) or 0),
            findings_worst=tuple(findings.get("dringendste") or ()),
            pending=int(requests.get("wartend", 0) or 0),
            processing=int(requests.get("laufend", 0) or 0),
            failed_7d=int(requests.get("fehlgeschlagen_7d", 0) or 0),
            movies=int(library.get("filme", 0) or 0),
            series=int(library.get("serien", 0) or 0),
            used_bytes=int(library.get("belegt_bytes", 0) or 0),
            free_bytes=int(library.get("frei_bytes", 0) or 0),
            open_tickets=int(raw.get("tickets_offen", 0) or 0),
            instances=tuple(Instance.from_json(i) for i in raw.get("instanzen") or ()),
        )


@dataclass(slots=True)
class Snapshot:
    """Everything one poll collected, however much that turned out to be.

    ⚠️ **Missing is not an error here.** A key without ``verwalten`` gets no
    tile at all, and the integration simply creates fewer entities. Only
    ``identity`` is always present - without it there would be nothing to
    decide from.
    """

    identity: Identity
    tile: Tile | None = None
    pending_count: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)
