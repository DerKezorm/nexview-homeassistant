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


def _is_allowed(kind: str, hit: str) -> bool:
    if kind == "a mail address":
        return hit.lower().endswith(ALLOWED_MAIL_DOMAINS)
    return False


def test_nothing_personal_is_committed() -> None:
    files = _tracked_files()
    # ⚠️ A loop over nothing passes. This guard has to see something.
    assert len(files) >= 15, f"Only found {len(files)} files to read - is the path right?"

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

    assert findings == [], (
        "Something personal would be committed to a public repository:\n  "
        + "\n  ".join(findings)
        + "\n\nUse example.com for addresses, a made-up host name for addresses, "
        "and never paste a real key. If one of these is a false alarm, widen "
        "ALLOWED_MAIL_DOMAINS rather than deleting the check."
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
