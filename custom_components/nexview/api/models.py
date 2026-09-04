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


def _ganzzahl(wert: Any) -> int | None:
    """``None`` bleibt ``None``, alles Zählbare wird eine Zahl.

    Der Unterschied trägt: keine Warteschlange gemessen ist etwas anderes als
    eine leere.
    """
    if wert is None:
        return None
    try:
        return int(wert)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class Instance:
    """One Radarr or Sonarr behind Nexview."""

    name: str
    reachable: bool
    problems: int
    #: Stable per installation, and the thing entities are keyed on. The name
    #: is what a person renames on a whim.
    key: str = ""
    version: str | None = None
    #: What the instance itself complains about, as plain sentences from
    #: Radarr or Sonarr. Kept for a diagnostic download, never for an
    #: attribute - a list on a sensor is exactly what Home Assistant is
    #: retiring.
    problem_texts: tuple[str, ...] = ()
    #: How much is queued at this instance right now, and how much of that is
    #: stuck. Nexview measures both; the second is the interesting one.
    queue: int | None = None
    queue_stuck: int | None = None
    #: Titles this instance wants and does not have. Nexview counts them per
    #: instance, in titles for Radarr and in episodes for Sonarr.
    gaps: int | None = None
    #: Whether Radarr or Sonarr actually calls Nexview back. Without it
    #: Nexview polls them, which is slower and which nobody notices.
    webhook_active: bool | None = None

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Instance:
        """From the dashboard tile, which counts problems but does not name them."""
        return cls(
            name=str(raw.get("name", "")),
            reachable=bool(raw.get("erreichbar", False)),
            problems=int(raw.get("probleme", 0) or 0),
            key=str(raw.get("kennung") or raw.get("name") or ""),
        )

    @classmethod
    def from_analysis(cls, raw: dict[str, Any]) -> Instance:
        """From Nexview's own analysis, which knows everything in one call.

        ⚠️ **One call instead of two.** The connection and health endpoints
        each know half of this; the analysis knows all of it, plus the queue
        and the state of the way back from Radarr and Sonarr. It is measured
        rather than live - ``gemessen_am`` says when - which is exactly right
        for something asked every thirty seconds.
        """
        meldungen = list(raw.get("meldungen") or ())
        return cls(
            name=str(raw.get("name", "")),
            reachable=bool(raw.get("erreichbar", False)),
            problems=len(meldungen),
            key=str(raw.get("kennung", "")),
            version=raw.get("version") or None,
            problem_texts=tuple(
                str(m.get("text", m)) if isinstance(m, dict) else str(m)
                for m in meldungen
            ),
            queue=_ganzzahl(raw.get("warteschlange")),
            queue_stuck=_ganzzahl(raw.get("warteschlange_haengt")),
            gaps=_ganzzahl(raw.get("luecken")),
            webhook_active=(
                bool(raw["rueckkanal_aktiv"]) if "rueckkanal_aktiv" in raw else None
            ),
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
    #: Wieviel vom belegten Platz dem Haus gehoert und bei niemandem zaehlt.
    #: 0 bei einem Nexview vor 0.31, das dieses Feld noch nicht kennt.
    house_bytes: int
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
            house_bytes=int(library.get("hausbestand_bytes", 0) or 0),
            free_bytes=int(library.get("frei_bytes", 0) or 0),
            open_tickets=int(raw.get("tickets_offen", 0) or 0),
            instances=tuple(Instance.from_json(i) for i in raw.get("instanzen") or ()),
        )


@dataclass(frozen=True, slots=True)
class Quota:
    """One allowance: how much is used, and how much there is.

    ``limit is None`` means unlimited, which is not the same as zero and must
    never be shown as one.
    """

    used: int
    limit: int | None

    @property
    def unlimited(self) -> bool:
        return self.limit is None

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(self.limit - self.used, 0)

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.used >= self.limit


@dataclass(frozen=True, slots=True)
class AccountUsage:
    """What one Nexview account has used up.

    ⚠️ **Name and number, nothing else.** Nexview's user list also carries
    mail addresses, linked media server accounts and avatar paths. None of it
    is read here: Home Assistant writes what it is given into a database that
    keeps everything forever, and none of that belongs in a home automation
    system.
    """

    user_id: int
    username: str
    name: str
    movies: Quota
    series: Quota
    storage: Quota
    #: Requests of this account still waiting for a decision.
    pending: int = 0
    #: Wann sich dieses Konto zuletzt angemeldet hat, als ISO-Zeitpunkt.
    #: ``None`` heisst: noch nie, oder Nexview ist aelter als 0.31.
    #:
    #: ⚠️ **Ein Zeitpunkt, kein Verlauf.** Wer wissen will, welche Konten
    #: eingeschlafen sind, sieht es hier auf einen Blick. Was jemand wann
    #: getan hat, bleibt drueben - eine Anwesenheitsliste gehoert nicht in
    #: eine Datenbank, die alles jahrelang behaelt.
    last_login: str | None = None

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> AccountUsage:
        def zahl(wert: Any) -> int:
            return int(wert or 0)

        def grenze(wert: Any) -> int | None:
            # ``None`` and the string "standard" both mean "no number of its
            # own here"; only a real figure is a limit.
            return int(wert) if isinstance(wert, (int, float)) else None

        return cls(
            user_id=int(raw.get("user_id", 0)),
            username=str(raw.get("username", "")),
            name=str(raw.get("display_name") or raw.get("username", "")),
            movies=Quota(
                zahl(raw.get("quota_movie_used")),
                grenze(raw.get("quota_movie_limit")),
            ),
            series=Quota(
                zahl(raw.get("quota_series_used")),
                grenze(raw.get("quota_series_limit")),
            ),
            storage=Quota(
                zahl(raw.get("storage_used_bytes")),
                grenze(raw.get("storage_limit_bytes")),
            ),
            pending=zahl(raw.get("pending")),
            last_login=(raw.get("last_login_at") or None),
        )


@dataclass(frozen=True, slots=True)
class Personal:
    """Was dieser Schlüssel über sein eigenes Konto weiß.

    ⚠️ **Der Teil, den jeder bekommt.** Alles andere hängt an Rechten, die ein
    persönlicher Schlüssel nicht hat - und ohne das hier bliebe von so einem
    Zugang nichts übrig als "Nexview antwortet". Die vier Adressen dahinter
    stehen alle unter Nexviews Stabilitätszusage, was diesen Teil zum
    verlässlichsten der ganzen Integration macht.
    """

    movies: Quota
    series: Quota
    storage: Quota
    #: Titel, die dem eigenen Konto zugerechnet sind.
    items: int = 0
    unread: int = 0
    open_tickets: int = 0
    #: Bekommt dieses Konto ueberhaupt Titel zugerechnet?
    #:
    #: ⚠️ **Bei einem Administrator nicht, und zwar strukturell.** Was er holt,
    #: gehoert in Nexview dem Haus: Er hat keine Grenze, ihm etwas
    #: zuzurechnen erfuellt keinen Zweck und verfaelscht die Uebersicht.
    #: ``items`` und der belegte Platz stehen bei ihm deshalb dauerhaft auf
    #: null - nicht, weil er nichts geholt hat, sondern weil es woanders
    #: gebucht wird. Nexview sagt das selbst, damit hier keine Regel
    #: nachgebaut wird, die sich drueben aendern kann.
    attributable: bool = True
    #: Wann das Kontingent zurückgesetzt wird, als ISO-Zeitpunkt. ``None`` bei
    #: einem Kontingent ohne Zeitraum.
    resets_at: str | None = None

    @property
    def exhausted(self) -> bool:
        return self.movies.exhausted or self.series.exhausted or self.storage.exhausted

    @classmethod
    def from_json(
        cls,
        quota: dict[str, Any],
        storage: dict[str, Any],
        unread: int,
        tickets: int,
    ) -> Personal:
        def teil(roh: dict[str, Any]) -> Quota:
            grenze = roh.get("limit")
            return Quota(
                used=int(roh.get("used") or 0),
                limit=int(grenze) if isinstance(grenze, (int, float)) else None,
            )

        film = quota.get("movie") or {}
        serie = quota.get("tv") or {}
        speichergrenze = storage.get("limit_bytes")
        return cls(
            movies=teil(film),
            series=teil(serie),
            storage=Quota(
                used=int(storage.get("used_bytes") or 0),
                limit=(
                    int(speichergrenze)
                    if isinstance(speichergrenze, (int, float))
                    else None
                ),
            ),
            items=int(storage.get("items") or 0),
            attributable=bool(storage.get("zurechenbar", True)),
            unread=unread,
            open_tickets=tickets,
            resets_at=film.get("resets_at") or serie.get("resets_at") or None,
        )


@dataclass(frozen=True, slots=True)
class MediaServer:
    """One Plex, Jellyfin or Emby behind Nexview.

    ⚠️ **No names of who is watching.** Nexview knows the account, the device
    and the title of every stream; none of that is kept here. What a device
    shows is how many are running, and the rest is available through an action
    for whoever asks for it in the moment.
    """

    key: str
    provider: str
    name: str
    #: Titles Nexview found on this server. ``None`` when the comparison has
    #: not run - which is not the same as an empty library.
    titles: int | None = None
    playing: int = 0
    transcoding: int = 0
    configured: bool = True


@dataclass(frozen=True, slots=True)
class Release:
    """One upcoming title, as the calendar sees it."""

    key: str
    title: str
    date: str
    media_type: str
    episode: str | None
    summary: str | None

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Release:
        folge = raw.get("episode_label") or None
        titel = raw.get("episode_title") or None
        return cls(
            key=str(raw.get("key", "")),
            title=str(raw.get("title", "")),
            date=str(raw.get("date") or raw.get("release_date") or ""),
            media_type=str(raw.get("media_type", "")),
            episode=" ".join(str(t) for t in (folge, titel) if t) or None,
            summary=(raw.get("overview") or None),
        )


@dataclass(frozen=True, slots=True)
class Version:
    """What Nexview says about its own version."""

    installed: str
    latest: str | None
    update_available: bool
    release_url: str | None

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Version:
        return cls(
            installed=str(raw.get("version", "")),
            latest=raw.get("latest_version") or None,
            update_available=bool(raw.get("update_available", False)),
            release_url=raw.get("release_url") or None,
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
    #: Keyed by instance key, so an entity finds its own again after a rename.
    instances: dict[str, Instance] = field(default_factory=dict)
    #: Keyed by account id, and only the accounts somebody asked for.
    accounts: dict[int, AccountUsage] = field(default_factory=dict)
    #: Keyed by server id, as Nexview numbers them.
    servers: dict[str, MediaServer] = field(default_factory=dict)
    #: How long the oldest request has been waiting, in hours. ``None`` when
    #: nothing is waiting - which a zero would read as "somebody just asked".
    oldest_pending_hours: float | None = None
    version: Version | None = None
    #: Das eigene Konto. Das Einzige, was jeder Schlüssel lesen darf.
    personal: Personal | None = None
    extra: dict[str, Any] = field(default_factory=dict)
