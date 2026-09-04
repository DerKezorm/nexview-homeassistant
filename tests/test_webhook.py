"""The way back, which is the piece with the most moving parts.

Two things are checked here. That an incoming call becomes the right event -
including one Nexview has not invented yet. And that the integration can set
itself up over in Nexview without anybody copying a four digit code between two
browser tabs, which is the whole reason the payload carries that code in a
field of its own.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.nexview.const import DOMAIN, POLL_IDLE, POLL_PUSHED

from .conftest import URL, WEBHOOK_ID, setup_entry


def _payload(event: str, **extra: Any) -> dict[str, Any]:
    return {
        "source": "nexview",
        "event": event,
        "level": "high",
        "title": "Dune",
        "body": "waiting for a decision",
        "image": None,
        "url": f"{URL}/admin/requests",
        "code": None,
        **extra,
    }


async def _call_webhook(hass_client_no_auth, payload: dict[str, Any]):
    client = await hass_client_no_auth()
    return await client.post(f"/api/webhook/{WEBHOOK_ID}", json=payload)


class TestIncomingCalls:
    """Only the receiving half. Setting itself up is the next class down."""

    @pytest.fixture(autouse=True)
    def already_enrolled(self):
        with patch(
            "custom_components.nexview.webhook.NexviewWebhook.async_ensure_target",
            AsyncMock(return_value=True),
        ):
            yield

    async def test_a_waiting_request_becomes_an_event(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        hass_client_no_auth,
    ) -> None:
        await setup_entry(hass, entry)

        await _call_webhook(hass_client_no_auth, _payload("request_pending"))
        await hass.async_block_till_done()

        state = hass.states.get("event.nexview_admin_requests")
        assert state is not None
        assert state.attributes["event_type"] == "pending"
        assert state.attributes["title"] == "Dune"

    async def test_storage_and_requests_stay_apart(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        hass_client_no_auth,
    ) -> None:
        """⚠️ The reason there are three entities and not one.

        Somebody automating on requests must not be woken by a storage
        message. With a single event entity every automation would have to
        check first whether the event was even its own.
        """
        await setup_entry(hass, entry)

        await _call_webhook(hass_client_no_auth, _payload("storage_released"))
        await hass.async_block_till_done()

        storage = hass.states.get("event.nexview_admin_storage")
        requests = hass.states.get("event.nexview_admin_requests")
        assert storage.attributes["event_type"] == "released"
        assert requests.state == "unknown", "The requests entity must not have fired."

    async def test_an_unknown_notification_is_not_dropped(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        hass_client_no_auth,
    ) -> None:
        """⚠️ Nexview will grow notification types this version never saw.

        Swallowing them silently makes the integration look broken to whoever
        waits for an automation that never fires. They land on the operations
        entity, carrying their original name.
        """
        await setup_entry(hass, entry)

        await _call_webhook(hass_client_no_auth, _payload("something_new_entirely"))
        await hass.async_block_till_done()

        state = hass.states.get("event.nexview_admin_operations")
        assert state.attributes["event_type"] == "other"
        assert state.attributes["nexview_event"] == "something_new_entirely"

    async def test_a_call_from_somewhere_else_fires_nothing(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        hass_client_no_auth,
    ) -> None:
        """The address is not a secret worth relying on by itself."""
        await setup_entry(hass, entry)

        response = await _call_webhook(
            hass_client_no_auth, {"source": "somebody_else", "event": "request_pending"}
        )
        await hass.async_block_till_done()

        assert response.status == 200, "Never answer an error - it only earns a retry."
        assert hass.states.get("event.nexview_admin_requests").state == "unknown"


class TestSettingItselfUp:
    async def test_it_catches_its_own_confirmation_code(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        hass_client_no_auth,
    ) -> None:
        """⚠️ The point of the whole exercise.

        Nexview refuses to save a target that has not proven itself: it sends
        a test message with a four digit code, and only a caller who reads it
        back may save. Good rule - an HTTP 200 from a push service means
        "accepted", not "arrived" - and it works for a machine too, as long as
        the machine can find the code. It can, because the payload carries it
        in its own field instead of only inside a translated sentence.
        """
        confirmed: list[str] = []

        async def send_test_message(
            name: str, url: str, language: str = "en"
        ) -> None:
            # Nexview calls us while its own request is still open.
            await _call_webhook(hass_client_no_auth, _payload("test", code="4711"))


        with (
            patch(
                "custom_components.nexview.api.NexviewClient.push_register",
                AsyncMock(side_effect=send_test_message),
            ),
            patch(
                "custom_components.nexview.api.NexviewClient.push_confirm",
                AsyncMock(side_effect=lambda code: confirmed.append(code)),
            ),
        ):
            await setup_entry(hass, entry)

        assert confirmed == ["4711"], "The code from the payload had to come back."
        # Asked of the coordinator, not of the diagnostic sensor: that one is
        # deliberately switched off until somebody turns it on.
        assert entry.runtime_data.pushing is True
        assert entry.runtime_data.update_interval == POLL_PUSHED, (
            "With the way back in place, asking every 30 seconds is waste."
        )

    async def test_the_test_message_does_not_become_news(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        hass_client_no_auth,
    ) -> None:
        """A confirmation is a handshake, not something that happened."""

        async def send_test_message(
            name: str, url: str, language: str = "en"
        ) -> None:
            await _call_webhook(hass_client_no_auth, _payload("test", code="1234"))


        with (
            patch(
                "custom_components.nexview.api.NexviewClient.push_register",
                AsyncMock(side_effect=send_test_message),
            ),
            patch(
                "custom_components.nexview.api.NexviewClient.push_confirm",
                AsyncMock(),
            ),
        ):
            await setup_entry(hass, entry)

        assert hass.states.get("event.nexview_admin_operations").state == "unknown"

    async def test_an_existing_target_is_left_alone(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        """⚠️ Never rewrite what is already there and working.

        An integration that re-registers itself on every restart quietly undoes
        whatever a person adjusted by hand over there.
        """
        from .conftest import IDENTITY_ADMIN, TILE

        known_url = f"http://ha.test:8123/api/webhook/{WEBHOOK_ID}"

        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_ADMIN)
        aioclient_mock.get(f"{URL}/api/v1/dashboard", json=TILE)
        aioclient_mock.get(
            f"{URL}/api/v1/admin/requests/pending/count", json={"pending": 4}
        )
        aioclient_mock.get(
            f"{URL}/api/v1/me/push",
            json={"eingerichtet": True, "bestaetigt": True, "url": known_url},
        )

        with (
            patch(
                "custom_components.nexview.webhook.NexviewWebhook.url",
                new_callable=PropertyMock,
                return_value=known_url,
            ),
            patch(
                "custom_components.nexview.api.NexviewClient.push_register", AsyncMock()
            ) as sent,
        ):
            await setup_entry(hass, entry)

        assert sent.call_count == 0, "It sent a test message for a target it already had."


class TestTheLanguage:
    async def test_nexview_is_asked_in_the_language_of_this_home_assistant(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        hass_client_no_auth,
    ) -> None:
        """⚠️ Die Meldungen sind Saetze, keine Kennungen.

        Der Bestaetigungscode steht in einem eigenen Feld und braucht keine
        Sprache. Alles danach traegt ``title`` und ``body`` als fertigen Text,
        und der landet in einer Benachrichtigung, die jemand liest. Fest auf
        Englisch hiess: "New ticket" in einem deutschen Haushalt.
        """
        hass.config.language = "de"
        gefragt: list[str] = []

        async def testnachricht(name: str, url: str, language: str = "en") -> None:
            gefragt.append(language)
            await _call_webhook(hass_client_no_auth, _payload("test", code="4711"))


        with (
            patch(
                "custom_components.nexview.api.NexviewClient.push_register",
                AsyncMock(side_effect=testnachricht),
            ),
            patch(
                "custom_components.nexview.api.NexviewClient.push_confirm",
                AsyncMock(),
            ),
        ):
            await setup_entry(hass, entry)

        assert gefragt == ["de"], (
            "Nexview wurde nicht in der Sprache dieser Instanz gefragt."
        )

    async def test_anything_that_is_not_german_gets_english(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        hass_client_no_auth,
    ) -> None:
        """Nexview kennt genau zwei Sprachen. Alles andere bekommt Englisch."""
        hass.config.language = "fr"
        gefragt: list[str] = []

        async def testnachricht(name: str, url: str, language: str = "en") -> None:
            gefragt.append(language)
            await _call_webhook(hass_client_no_auth, _payload("test", code="4711"))

        with (
            patch(
                "custom_components.nexview.api.NexviewClient.push_register",
                AsyncMock(side_effect=testnachricht),
            ),
            patch(
                "custom_components.nexview.api.NexviewClient.push_confirm",
                AsyncMock(),
            ),
        ):
            await setup_entry(hass, entry)

        assert gefragt == ["en"]

    async def _stand(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        *,
        gemeldet: dict[str, object],
    ) -> AsyncMock:
        """Aufbauen gegen ein Nexview, das `gemeldet` ueber das Ziel sagt.

        ⚠️ **``push_state`` wird gepatcht, nicht als HTTP-Mock gesetzt.** Die
        Kulisse belegt ``/api/v1/me/push`` bereits, und beim Mocker gewinnt der
        zuerst registrierte Eintrag - ein zweiter daneben waere wirkungslos
        gewesen, und der Test haette geprueft, was die Kulisse sagt.
        """
        known_url = f"http://ha.test:8123/api/webhook/{WEBHOOK_ID}"
        stand = {"eingerichtet": True, "bestaetigt": True, "url": known_url}
        stand.update(gemeldet)

        with (
            patch(
                "custom_components.nexview.webhook.NexviewWebhook.url",
                new_callable=PropertyMock,
                return_value=known_url,
            ),
            patch(
                "custom_components.nexview.api.NexviewClient.push_state",
                AsyncMock(return_value=stand),
            ),
            patch(
                "custom_components.nexview.api.NexviewClient.push_register", AsyncMock()
            ) as sent,
        ):
            await setup_entry(hass, entry)
        return sent

    async def test_the_same_language_is_left_alone(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
    ) -> None:
        """Nothing to do, so nothing is sent."""
        hass.config.language = "en"
        sent = await self._stand(
            hass, entry, nexview, gemeldet={"language": "en"}
        )
        assert sent.call_count == 0, "It re-registered a target that was already right."

    async def test_a_changed_language_is_registered_again(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
    ) -> None:
        """⚠️ The address is right, the language is not, and that counts.

        Somebody switched this Home Assistant to German after setting the
        integration up. Without this, Nexview would keep sending English
        sentences for as long as the target stands, and nothing would say why.
        """
        hass.config.language = "de"
        sent = await self._stand(
            hass, entry, nexview, gemeldet={"language": "en"}
        )
        assert sent.call_count == 1, (
            "The language changed and the target was left as it was. Nexview "
            "goes on sending in the old language until somebody disconnects it "
            "by hand."
        )
        assert sent.call_args.args[2] == "de", (
            f"Registered again, but in {sent.call_args.args[2]!r} rather than "
            "the language this Home Assistant is now set to."
        )

    async def test_a_nexview_that_reports_no_language_is_left_alone(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
    ) -> None:
        """⚠️ A missing field is not a mismatch.

        Read strictly, `None != "de"` would mean re-registering on every single
        restart, each time with a test message, against anything that does not
        report the language back.
        """
        hass.config.language = "de"
        sent = await self._stand(hass, entry, nexview, gemeldet={})
        assert sent.call_count == 0, (
            "It re-registered because the other side said nothing about the "
            "language. That repeats on every restart."
        )


class TestWhenNexviewCannotReachUs:
    async def test_it_says_so_instead_of_going_quiet(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ The gap the Seerr integration leaves open.

        Everything keeps working without the push - Home Assistant just asks
        more often - but events arrive late or never, and nothing on screen
        explains why. Seerr's own quality file claims there is no case for a
        repair issue here. There is, and this is it.
        """
        with patch(
            "custom_components.nexview.webhook.CODE_TIMEOUT", 0.05
        ), patch(
            "custom_components.nexview.api.NexviewClient.push_register",
            AsyncMock(),  # says it sent something; nothing ever arrives
        ):
            await setup_entry(hass, entry)

        issues = ir.async_get(hass)
        assert issues.async_get_issue(DOMAIN, f"push_missing_{entry.entry_id}")
        assert entry.runtime_data.pushing is False
        assert entry.runtime_data.update_interval == POLL_IDLE, (
            "Without the way back it has to ask often enough to stay useful."
        )

class TestTheSwitch:
    """Der Haken in den Optionen: Nexview darf anrufen, oder eben nicht.

    ⚠️ **Er steht nicht im Einrichtungsassistenten, und das ist Absicht.** Wer
    die Integration einrichtet, hat noch keine Vorstellung davon, was ein
    Rueckkanal ist; eine Frage, die man nicht beantworten kann, macht den
    Einstieg schlechter. Gebraucht wird er hinterher - naemlich dann, wenn
    Nexview dieses Home Assistant nicht erreicht und die Reparaturmeldung bei
    jedem Neustart wiederkommt.
    """

    async def test_off_means_nexview_is_asked_to_forget_us(
        self, hass: HomeAssistant, nexview: AiohttpClientMocker
    ) -> None:
        from custom_components.nexview.const import CONF_PUSH

        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=f"{URL}::1",
            data={"url": URL, "api_key": "nxv_" + "t" * 40, "webhook_id": WEBHOOK_ID},
            options={CONF_PUSH: False},
        )

        with (
            patch(
                "custom_components.nexview.api.NexviewClient.push_register",
                AsyncMock(),
            ) as angemeldet,
            patch(
                "custom_components.nexview.api.NexviewClient.push_remove",
                AsyncMock(),
            ) as vergessen,
        ):
            await setup_entry(hass, entry)

        assert angemeldet.call_count == 0, "Es hat sich trotzdem angemeldet."
        assert vergessen.call_count == 1, (
            "Ohne das Abmelden funkte Nexview weiter an eine Adresse, die "
            "niemand mehr hoeren will."
        )
        assert entry.runtime_data.pushing is False

    async def test_off_also_silences_the_repair_notice(
        self, hass: HomeAssistant, nexview: AiohttpClientMocker
    ) -> None:
        """Ein Hinweis auf etwas, das jemand gerade abgeschaltet hat, ist keiner."""
        from custom_components.nexview.const import CONF_PUSH

        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=f"{URL}::1",
            data={"url": URL, "api_key": "nxv_" + "t" * 40, "webhook_id": WEBHOOK_ID},
            options={CONF_PUSH: False},
        )

        with patch(
            "custom_components.nexview.api.NexviewClient.push_remove", AsyncMock()
        ):
            await setup_entry(hass, entry)

        issues = ir.async_get(hass)
        for kennung in ("push_missing", "push_too_old"):
            assert (
                issues.async_get_issue(DOMAIN, f"{kennung}_{entry.entry_id}") is None
            ), f"{kennung} steht, obwohl der Rueckkanal abgeschaltet ist."

    async def test_an_older_nexview_gets_its_own_sentence(
        self, hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock
    ) -> None:
        """⚠️ Zwei Ursachen, zwei Meldungen.

        Ein Nexview vor 0.30 kennt die Adresse dafuer nicht. Wer in diesem Fall
        die Meldung "Nexview erreicht dieses Home Assistant nicht" bekaeme,
        suchte am falschen Ort - naemlich im Netzwerk statt im Update.
        """
        from .conftest import ABOUT, IDENTITY_ADMIN, MY_STORAGE, QUOTA, TILE

        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_ADMIN)
        aioclient_mock.get(f"{URL}/api/v1/dashboard", json=TILE)
        aioclient_mock.get(
            f"{URL}/api/v1/admin/requests/pending/count", json={"pending": 0}
        )
        # Ein aelteres Nexview kennt diese Adresse nicht.
        aioclient_mock.get(f"{URL}/api/v1/me/push", status=404)
        aioclient_mock.get(f"{URL}/api/admin/analyse", json={})
        aioclient_mock.get(f"{URL}/api/admin/analyse/laufend", json={})
        aioclient_mock.get(f"{URL}/api/admin/stats", json={})
        aioclient_mock.get(f"{URL}/api/admin/requests", json=[])
        aioclient_mock.get(f"{URL}/api/calendar", json={"days": []})
        aioclient_mock.get(f"{URL}/api/v1/about", json=ABOUT)
        aioclient_mock.get(f"{URL}/api/v1/requests/quota", json=QUOTA)
        aioclient_mock.get(f"{URL}/api/v1/storage/me", json=MY_STORAGE)
        aioclient_mock.get(
            f"{URL}/api/v1/notifications/unread/count", json={"unread": 0}
        )
        aioclient_mock.get(f"{URL}/api/v1/tickets/open-count", json={"count": 0})
        aioclient_mock.get(
            f"{URL}/api/settings/qualitaetsprofile/medienserver",
            json={"server": [], "instanzen": [], "warnungen": []},
        )

        await setup_entry(hass, entry)

        issues = ir.async_get(hass)
        assert issues.async_get_issue(DOMAIN, f"push_too_old_{entry.entry_id}")
        assert (
            issues.async_get_issue(DOMAIN, f"push_missing_{entry.entry_id}") is None
        ), "Beide Meldungen zugleich waeren zwei Erklaerungen fuer eine Ursache."

class TestDeletingTheIntegration:
    """⚠️ Gefragt worden, bevor irgendein Test es geprueft hatte.

    "Werden die eigentlich geloescht, wenn ich die Integration in HA loesche?
    Sonst funken die ja immer ins Leere." Sie wurden nicht. Nexview haette
    weiter eine Adresse angerufen, an der niemand mehr zuhoert, seinen
    Postausgang mit Fehlversuchen gefuellt und dem Betreiber eine Zeile
    hinterlassen, deren Anbindung es seit Wochen nicht mehr gibt.
    """

    async def test_removing_it_withdraws_the_callback(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        await setup_entry(hass, entry)

        with patch(
            "custom_components.nexview.api.NexviewClient.push_remove", AsyncMock()
        ) as abgemeldet:
            assert await hass.config_entries.async_remove(entry.entry_id)
            await hass.async_block_till_done()

        assert abgemeldet.call_count == 1, (
            "Nexview wurde nicht gesagt, dass dieses Home Assistant weg ist."
        )

    async def test_a_restart_does_not_withdraw_anything(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Der Grund, warum das nicht in async_unload_entry steht.

        Entladen wird bei jedem Neustart und bei jeder Aenderung an den
        Optionen. Wuerde dort abgemeldet, brauchte jeder Neustart eine neue
        Anmeldung samt neuem Bestaetigungscode - und zwischendurch waere
        Nexview blind.
        """
        await setup_entry(hass, entry)

        with patch(
            "custom_components.nexview.api.NexviewClient.push_remove", AsyncMock()
        ) as abgemeldet:
            assert await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()

        assert abgemeldet.call_count == 0, "Ein Neustart hat den Rueckkanal abgemeldet."

    async def test_an_unreachable_nexview_does_not_block_the_delete(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """Wer loeschen will, soll loeschen koennen - auch wenn Nexview gerade aus ist.

        Der Rueckkanal bleibt dann drueben stehen. Genau dafuer gibt es die
        Liste beim Betreiber, in der eine Zeile mit einem Klick verschwindet.
        """
        from custom_components.nexview.api import NexviewConnectionError

        await setup_entry(hass, entry)

        with patch(
            "custom_components.nexview.api.NexviewClient.push_remove",
            AsyncMock(side_effect=NexviewConnectionError("weg")),
        ):
            assert await hass.config_entries.async_remove(entry.entry_id)
            await hass.async_block_till_done()

        assert hass.config_entries.async_get_entry(entry.entry_id) is None
