"""When Nexview says no, the actions say why, in the language of the reader.

Nexview 1.0 answers a refusal with an object: ``{"detail": {"code": ...,
"message": ...}}``. The code is the part meant for machines, the message a
German fallback for whoever reads without an interface. The integration reads
the code and translates it itself; the sentence from Nexview never reaches a
screen.

⚠️ **These tests go through HTTP, not through a patched client.** The older
ones patch ``NexviewClient.reject`` and so never saw what went over the wire,
which is how the reject body was wrong for every release before 0.1.4.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.nexview.const import (
    ATTR_REQUEST_ID,
    DOMAIN,
    SERVICE_APPROVE,
    SERVICE_CANCEL,
    SERVICE_DEFER,
    SERVICE_REJECT,
)

from .conftest import URL, setup_entry

#: Nexview's German fallback, as 1.0.0 sends it. It must never show.
SATZ = "Das Konto hat keine Grenze überzogen; Freigeben oder ablehnen."


@pytest.fixture(autouse=True)
def no_webhook_enrolment():
    """The way back has its own test file. Here it only has to not get in the way."""
    with patch(
        "custom_components.nexview.webhook.NexviewWebhook.async_ensure_target",
        AsyncMock(return_value=True),
    ):
        yield


def _refusal(code: str, **extra: Any) -> dict[str, Any]:
    return {"detail": {"code": code, "message": SATZ, **extra}}


async def _call(hass: HomeAssistant, service: str, **data: Any) -> None:
    await hass.services.async_call(
        DOMAIN, service, {ATTR_REQUEST_ID: 42, **data}, blocking=True
    )


class TestDeferring:
    async def test_an_account_within_its_limits_is_named_as_the_reason(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Nexview 1.0 defers only for an account over its limits.

        Before, it said ``deferred`` and put the request back among the open
        approvals two minutes later. Now it answers 409, and "Nexview refused"
        would leave whoever wrote the automation guessing.
        """
        nexview.post(
            f"{URL}/api/admin/requests/42/defer",
            status=409,
            json=_refusal("defer_nothing_to_wait_for"),
        )
        await setup_entry(hass, entry)

        with pytest.raises(ServiceValidationError) as fehler:
            await _call(hass, SERVICE_DEFER)

        assert fehler.value.translation_key == "defer_nothing_to_wait_for"
        assert fehler.value.translation_placeholders == {"request_id": "42"}
        assert SATZ not in str(fehler.value)


class TestNotWaitingAnyMore:
    @pytest.mark.parametrize(
        ("service", "path"),
        [
            (SERVICE_APPROVE, "approve"),
            (SERVICE_REJECT, "reject"),
            (SERVICE_DEFER, "defer"),
        ],
    )
    async def test_a_decided_request_is_named_as_such(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        service: str,
        path: str,
    ) -> None:
        nexview.post(
            f"{URL}/api/admin/requests/42/{path}",
            status=409,
            json=_refusal("request_not_pending"),
        )
        await setup_entry(hass, entry)

        with pytest.raises(ServiceValidationError) as fehler:
            await _call(hass, service)

        assert fehler.value.translation_key == "request_not_pending"
        assert fehler.value.translation_placeholders == {"request_id": "42"}


class TestWhenRadarrOrNexcrateFails:
    """Approving hands the request on, cancelling takes it back out.

    Both can fail at Radarr, Sonarr or nexcrate, and Nexview 1.0 names the
    code and the service instead of answering with a German sentence.
    """

    @pytest.mark.parametrize(
        ("code", "extra", "key", "service_name"),
        [
            ("arr_timeout", {"service": "Radarr"}, "procurement_unreachable", "Radarr"),
            (
                "arr_unreachable",
                {"service": "Sonarr", "url": "http://sonarr:8989"},
                "procurement_unreachable",
                "Sonarr",
            ),
            ("nexcrate_unavailable", {}, "procurement_unreachable", "nexcrate"),
            (
                "arr_key_rejected",
                {"service": "Radarr"},
                "procurement_key_rejected",
                "Radarr",
            ),
            ("nexcrate_scope_missing", {}, "procurement_key_rejected", "nexcrate"),
        ],
    )
    async def test_the_failing_service_is_named(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        code: str,
        extra: dict[str, Any],
        key: str,
        service_name: str,
    ) -> None:
        nexview.post(
            f"{URL}/api/admin/requests/42/approve",
            status=502,
            json=_refusal(code, **extra),
        )
        await setup_entry(hass, entry)

        with pytest.raises(HomeAssistantError) as fehler:
            await _call(hass, SERVICE_APPROVE)

        assert not isinstance(fehler.value, ServiceValidationError), (
            "A service that fails over there is not a wrong input over here."
        )
        assert fehler.value.translation_key == key
        assert fehler.value.translation_placeholders == {"service": service_name}

    async def test_a_version_radarr_still_feeds_is_explained(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """Right after switching to nexcrate, the refusal most people meet."""
        nexview.post(
            f"{URL}/api/admin/requests/42/approve",
            status=409,
            json=_refusal("nexcrate_version_fed_by_source"),
        )
        await setup_entry(hass, entry)

        with pytest.raises(ServiceValidationError) as fehler:
            await _call(hass, SERVICE_APPROVE)

        assert fehler.value.translation_key == "version_fed_by_source"

    async def test_any_other_code_of_theirs_is_passed_on_as_a_code(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        nexview.post(
            f"{URL}/api/admin/requests/42/cancel",
            status=502,
            json=_refusal("arr_http_error", service="Sonarr", status=500),
        )
        await setup_entry(hass, entry)

        with pytest.raises(HomeAssistantError) as fehler:
            await _call(hass, SERVICE_CANCEL)

        assert fehler.value.translation_key == "procurement_refused"
        assert fehler.value.translation_placeholders == {
            "service": "Sonarr",
            "code": "arr_http_error",
        }


class TestWhatNobodyKnowsYet:
    async def test_an_unknown_code_falls_back_and_shows_the_code(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """A Nexview newer than this integration may refuse for a new reason.

        That must still read as a refusal, with the code to search for, and
        still without Nexview's sentence.
        """
        nexview.post(
            f"{URL}/api/admin/requests/42/approve",
            status=409,
            json=_refusal("something_from_the_future"),
        )
        await setup_entry(hass, entry)

        with pytest.raises(HomeAssistantError) as fehler:
            await _call(hass, SERVICE_APPROVE)

        assert fehler.value.translation_key == "request_failed"
        fehlertext = fehler.value.translation_placeholders["error"]
        assert "something_from_the_future" in fehlertext
        assert "409" in fehlertext
        assert SATZ not in fehlertext

    async def test_a_bare_sentence_falls_back_without_showing_it(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """Cancelling a request that is not running still answers a sentence."""
        nexview.post(
            f"{URL}/api/admin/requests/42/cancel",
            status=409,
            json={"detail": "Nur laufende Anfragen können abgebrochen werden."},
        )
        await setup_entry(hass, entry)

        with pytest.raises(HomeAssistantError) as fehler:
            await _call(hass, SERVICE_CANCEL)

        assert fehler.value.translation_key == "request_failed"
        assert "Nur laufende" not in fehler.value.translation_placeholders["error"]

    async def test_an_unknown_number_still_reads_as_one(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        nexview.post(
            f"{URL}/api/admin/requests/42/defer",
            status=404,
            json=_refusal("request_not_found"),
        )
        await setup_entry(hass, entry)

        with pytest.raises(ServiceValidationError) as fehler:
            await _call(hass, SERVICE_DEFER)

        assert fehler.value.translation_key == "unknown_request"


class TestRejecting:
    """⚠️ Found while checking the actions against Nexview 1.0.

    Nexview reads ``reason`` and requires a body. The integration sent
    ``grund``, and nothing at all without a reason, so a plain rejection
    answered 422 and a reason given was dropped without a word.
    """

    async def test_the_reason_arrives_under_its_name(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        nexview.post(f"{URL}/api/admin/requests/42/reject", json={"id": 42})
        await setup_entry(hass, entry)

        await _call(hass, SERVICE_REJECT, reason="Already there")

        gesendet = [c for c in nexview.mock_calls if str(c[1]).endswith("/reject")]
        assert gesendet[-1][2] == {"reason": "Already there"}

    async def test_without_a_reason_there_is_still_a_body(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        nexview.post(f"{URL}/api/admin/requests/42/reject", json={"id": 42})
        await setup_entry(hass, entry)

        await _call(hass, SERVICE_REJECT)

        gesendet = [c for c in nexview.mock_calls if str(c[1]).endswith("/reject")]
        assert gesendet[-1][2] == {}


class TestTheTexts:
    def test_every_refusal_has_a_text_in_both_languages(self) -> None:
        """A key without a text shows as a raw identifier in the trace.

        Checked against the keys the code actually raises, so a new one cannot
        be added without its two sentences.
        """
        from custom_components.nexview import REFUSAL_KEYS

        basis = Path(__file__).parent.parent / "custom_components" / "nexview"
        texte = {
            sprache: json.loads(
                (basis / "translations" / f"{sprache}.json").read_text("utf-8")
            )["exceptions"]
            for sprache in ("en", "de")
        }
        assert set(texte["en"]) == set(texte["de"])
        assert len(REFUSAL_KEYS) >= 6
        for key in REFUSAL_KEYS:
            for sprache in ("en", "de"):
                assert key in texte[sprache], f"{sprache}: {key} hat keinen Text"
            platz = {
                sprache: {
                    teil.split("}")[0]
                    for teil in texte[sprache][key]["message"].split("{")[1:]
                }
                for sprache in ("en", "de")
            }
            assert platz["en"] == platz["de"], f"{key}: Platzhalter weichen ab"
