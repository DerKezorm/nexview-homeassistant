"""The guard over the separation.

⚠️ **Why a test and not a note in the readme.** The whole point of keeping
``api/`` apart is that it can be lifted out into ``python-nexview`` on PyPI
without being rewritten, because the Home Assistant core requires a separate
library. That property is invisible: nothing breaks the day somebody imports a
Home Assistant helper in there for convenience, and it only surfaces months
later, when lifting it out turns into a rewrite.

So it is checked, and it is checked the blunt way - by reading the files, not
by importing them. An import test would pass just as well with
``homeassistant`` already loaded by something else.
"""

from __future__ import annotations

import ast
from pathlib import Path

API = Path(__file__).parent.parent / "custom_components" / "nexview" / "api"


def _modules() -> list[Path]:
    files = sorted(API.glob("*.py"))
    # ⚠️ A loop over an empty directory passes silently. If the package is
    # ever moved, this test has to fail rather than congratulate itself.
    assert len(files) >= 4, f"Expected the api package, found {files}"
    return files


def test_the_client_does_not_know_home_assistant() -> None:
    offenders: list[str] = []

    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name == "homeassistant" or name.startswith("homeassistant."):
                    offenders.append(f"{path.name}:{node.lineno} imports {name}")

    assert offenders == [], (
        "The api package imported Home Assistant:\n  "
        + "\n  ".join(offenders)
        + "\n\nIt has to stay a plain client. Anything that needs Home Assistant "
        "belongs in the integration next to it, not in here - otherwise this "
        "cannot become python-nexview on PyPI without a rewrite."
    )


def test_it_talks_over_a_session_it_was_given() -> None:
    """⚠️ No connection pool of its own.

    Building a session inside the client would work and is the obvious thing
    to write. It also means a second pool, a second set of timeouts and a
    connection that outlives the config entry. The quality scale asks for the
    shared one, and the constructor is where that is decided.
    """
    source = (API / "client.py").read_text(encoding="utf-8")
    assert "def __init__(self, session:" in source
    assert "aiohttp.ClientSession(" not in source, (
        "The client built its own session. It has to use the one handed in."
    )
