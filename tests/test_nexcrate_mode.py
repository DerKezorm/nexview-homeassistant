"""Nexview 1.0 with nexcrate instead of Radarr and Sonarr.

Two things change for the integration. The Radarr and Sonarr tools answer 409,
which ``test_media_servers.py`` covers for the one the integration reads. And
a health finding comes as a code with values instead of a sentence, so
``text`` is empty.
"""

from __future__ import annotations

from custom_components.nexview.api.models import Instance


def test_a_finding_without_a_sentence_shows_its_code() -> None:
    instanz = Instance.from_analysis(
        {
            "kennung": "nexcrate",
            "name": "nexcrate",
            "erreichbar": True,
            "meldungen": [
                {"text": "", "code": "disk_full", "params": {"free_bytes": 1}},
                {"text": "Radarr cannot reach the indexer", "code": ""},
            ],
        }
    )

    assert instanz.problem_texts == ("disk_full", "Radarr cannot reach the indexer")
