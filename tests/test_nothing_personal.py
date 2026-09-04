"""Nothing personal goes into this repository.

⚠️ **Because it is public and git remembers.** This integration is developed
against a real Nexview with real accounts, real mail addresses, real media
server names and real access keys. Any of it could slip into a docstring as a
"real example", into a test as convincing sample data, or into a committed log
file. Getting it out again means rewriting history, and by then it has been
cloned.

So the check is mechanical and runs with every test run: it reads every file
that would be committed and refuses anything that looks like it belongs to a
person.

⚠️ **The list of patterns is deliberately blunt.** A false positive costs one
rename; a false negative costs a published address.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent

#: Suffixes worth reading. Anything else (images, fonts) cannot carry a
#: readable address, and reading them would only slow this down.
TEXT_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".md", ".toml", ".txt", ".cfg"}

#: Addresses that are reserved for documentation and cannot reach anybody.
ALLOWED_MAIL_DOMAINS = (
    "example.com",
    "example.org",
    "example.net",
    "users.noreply.github.com",
)

PATTERNS: dict[str, re.Pattern[str]] = {
    "a mail address": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "a private network address": re.compile(
        r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"
    ),
    "a Nexview access key": re.compile(r"nxv_[A-Za-z0-9_-]{20,}"),
    # ``eyJ`` is what a base64 ``{"`` starts with, so every JWT begins that way.
    # The lengths are deliberately modest: a short header is still a token.
    "a bearer token": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
}


#: Words that belong to whoever runs this - names, host names, anything that
#: identifies a person or their household. One per line, ``#`` starts a
#: comment, matching is case-insensitive.
#:
#: ⚠️ **Not committed, and that is the point.** The list itself would be the
#: personal data it protects. It lives beside this file, git ignores it, and
#: the check says out loud when it is missing so that a green run in CI is not
#: mistaken for "the names were checked".
#:
#: Nexview has the same mechanism (``backend/tools/personendaten_pruefen.py``);
#: this is deliberately a small copy rather than a shared dependency between
#: two repositories that are released separately.
BLOCKLIST = ROOT / "tests" / ".personal-words"


def _blocked_words() -> list[str]:
    if not BLOCKLIST.exists():
        return []
    woerter = []
    for zeile in BLOCKLIST.read_text(encoding="utf-8").splitlines():
        wort = zeile.split("#", 1)[0].strip()
        if len(wort) >= 3:
            woerter.append(wort)
    return woerter


def _tracked_files() -> list[Path]:
    """Everything git would carry, so ignored files are not scanned.

    Falls back to walking the tree before the first commit exists.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split("\n")
        files = [ROOT / name for name in out if name.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        files = [
            p
            for p in ROOT.rglob("*")
            if p.is_file() and not any(part.startswith(".") for part in p.parts)
        ]
    return [p for p in files if p.suffix in TEXT_SUFFIXES and p.exists()]


#: Endungen, hinter denen eine Datei steht und keine Mailadresse.
#:
#: ⚠️ **``icon@2x.png`` ist der Fall, an dem das aufgefallen ist.** Das Muster
#: fuer Mailadressen trifft darauf, und der Waechter meldete den Dateinamen des
#: eigenen Logos als Fund. Ein Fehlalarm kostet zwar nur eine Umbenennung, aber
#: einer, den man nicht abstellen kann, bringt jemanden dazu, den Waechter
#: abzuschalten.
DATEIENDUNGEN = (
    ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".ico",
    ".css", ".js", ".json", ".md", ".txt", ".yaml", ".yml",
)


def _is_allowed(kind: str, hit: str) -> bool:
    if kind == "a mail address":
        klein = hit.lower()
        return klein.endswith(ALLOWED_MAIL_DOMAINS) or klein.endswith(DATEIENDUNGEN)
    return False


def test_nothing_personal_is_committed() -> None:
    files = _tracked_files()
    # ⚠️ A loop over nothing passes. This guard has to see something.
    assert len(files) >= 15, f"Only found {len(files)} files to read - is the path right?"

    woerter = [
        (wort, re.compile(r"\b" + re.escape(wort) + r"\b", re.IGNORECASE))
        for wort in _blocked_words()
    ]

    findings: list[str] = []
    for path in files:
        if path.name == Path(__file__).name:
            continue  # the patterns themselves live here
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            for kind, pattern in PATTERNS.items():
                for hit in pattern.findall(line):
                    if _is_allowed(kind, hit):
                        continue
                    findings.append(
                        f"{path.relative_to(ROOT)}:{line_no} looks like {kind}: {hit}"
                    )
            for wort, muster in woerter:
                if muster.search(line):
                    findings.append(
                        f"{path.relative_to(ROOT)}:{line_no} carries a personal "
                        f"word: {wort}"
                    )

    assert findings == [], (
        "Something personal would be committed to a public repository:\n  "
        + "\n  ".join(findings)
        + "\n\nUse example.com for addresses, a made-up host name for addresses, "
        "and never paste a real key. If one of these is a false alarm, widen "
        "ALLOWED_MAIL_DOMAINS rather than deleting the check."
    )


def test_the_word_list_is_there_or_says_so() -> None:
    """⚠️ A missing list has to be loud, not silent.

    The words that identify a household cannot be committed - they are the
    very thing this guard keeps out. So the list is ignored by git, and on any
    machine without it this check only sees the shapes: mail addresses,
    private network addresses, keys. That is fine, but it must not look like
    the names were checked too.

    A name once reached a public repository through a docstring, and getting
    it out again meant rewriting history.
    """
    woerter = _blocked_words()
    if not woerter:
        import warnings

        warnings.warn(
            f"{BLOCKLIST.name} is not here, so no names were checked - only "
            "the patterns. Create it (one word per line) before publishing.",
            stacklevel=2,
        )
        return
    assert all(len(w) >= 3 for w in woerter), (
        "A word shorter than three letters would match half the repository."
    )


def test_the_guard_would_actually_catch_something(tmp_path: Path) -> None:
    """⚠️ A green guard proves nothing unless it can go red.

    Checks the patterns against samples instead of trusting that a clean
    repository means a working check.
    """
    samples = {
        "a mail address": "somebody@somewhere.de",
        "a private network address": "192.168.1.50",
        "a Nexview access key": "nxv_" + "A" * 40,
        "a bearer token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0",
    }
    for kind, sample in samples.items():
        assert PATTERNS[kind].search(sample), f"{kind} would have slipped through"
        assert not _is_allowed(kind, sample)

    # And the documented exception still has to be allowed through.
    assert _is_allowed("a mail address", "someone@example.com")
