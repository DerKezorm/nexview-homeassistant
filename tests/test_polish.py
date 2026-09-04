"""Diagnostics, system health, and changing the address without starting over.

⚠️ **The diagnostics test is the important one here.** That file gets attached
to public issue reports by people who want help, and it stays there. If a key
or an address ever leaks into it, it leaks to everybody who reads the issue.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.nexview.const import CONF_KEY, CONF_URL, DOMAIN
from custom_components.nexview.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import IDENTITY_ADMIN, IDENTITY_USER, KEY, URL, WEBHOOK_ID, setup_entry


def _wert(hass: HomeAssistant, entry: MockConfigEntry, unique: str) -> float | None:
    """Der Zahlenwert eines Eintrags, ueber seine dauerhafte Kennung gesucht."""
    registry = er.async_get(hass)
    kennung = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{unique}"
    )
    assert kennung, f"Keine Entitaet fuer {unique}"
    zustand = hass.states.get(kennung)
    return None if zustand is None else float(zustand.state)


@pytest.fixture(autouse=True)
def no_webhook_enrolment():
    with patch(
        "custom_components.nexview.webhook.NexviewWebhook.async_ensure_target",
        AsyncMock(return_value=True),
    ):
        yield


class TestDiagnostics:
    async def test_nothing_secret_comes_out(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Three secrets, and all three have to be gone.

        The key is obvious. The address is not: it says where somebody's
        installation lives. And the webhook id is a secret in its own right -
        anybody holding it can post events into that Home Assistant.
        """
        await setup_entry(hass, entry)

        report = str(await async_get_config_entry_diagnostics(hass, entry))

        assert KEY not in report, "The access key was in the diagnostics."
        assert URL not in report, "The address of the installation was in there."
        assert WEBHOOK_ID not in report, "The webhook id was in there."
        assert "REDACTED" in report, "Nothing was redacted at all - is the list right?"

    async def test_it_answers_the_questions_that_help(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """What a missing entity actually comes down to: what the key may do."""
        await setup_entry(hass, entry)

        report = await async_get_config_entry_diagnostics(hass, entry)

        assert report["key"]["may"] == [
            "anfragen",
            "einrichten",
            "entscheiden",
            "lesen",
            "verwalten",
        ]
        assert report["key"]["read_only"] is False
        assert report["what_was_read"]["tile"] is True
        assert report["what_was_read"]["instances"] == 2
        assert report["connection"]["nexview_version"] == "0.30.0"

    async def test_no_names_of_people_or_titles(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Findings come as identifiers, instances as keys, accounts as a count.

        Nexview knows plenty that would be handy in a bug report and has no
        business in one: who requested what, what the operator called their
        instances, who has how much left.
        """
        await setup_entry(hass, entry)

        report = str(await async_get_config_entry_diagnostics(hass, entry))

        assert "Gast" not in report, "An account name reached the diagnostics."
        assert "Some Film" not in report, "A requested title reached the diagnostics."


class TestSystemHealth:
    async def test_it_says_whether_events_are_arriving(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """The one line worth having: everything works without the push, quietly worse."""
        from custom_components.nexview.system_health import system_health_info

        await setup_entry(hass, entry)

        info = await system_health_info(hass)
        assert info["connected"] == 1
        assert info["answering"] == 1
        assert info["receiving_events"] == 1
        assert info["nexview_version"] == "0.30.0"

    async def test_it_survives_having_nothing_connected(
        self, hass: HomeAssistant
    ) -> None:
        from custom_components.nexview.system_health import system_health_info

        assert await system_health_info(hass) == {"connected": 0}


class TestReconfigure:
    async def test_a_moved_nexview_keeps_its_entry(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        """⚠️ Moving must not cost anybody their history.

        A new port, a name instead of an IP, a proxy in front - all of that is
        the same Nexview, and re-adding it from scratch would leave every
        sensor starting from nothing.
        """
        neu = "http://nexview.example.com:8000"
        aioclient_mock.get(f"{neu}/api/v1/me", json=IDENTITY_ADMIN)
        entry.add_to_hass(hass)

        result = await entry.start_reconfigure_flow(hass)
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: neu, CONF_KEY: KEY}
        )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.data[CONF_URL] == neu
        assert entry.unique_id == f"{neu}::1"

    async def test_it_refuses_to_become_a_different_account(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        aioclient_mock: AiohttpClientMocker,
    ) -> None:
        """Otherwise every entity would keep its past while meaning somebody else."""
        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_USER)
        entry.add_to_hass(hass)

        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: URL, CONF_KEY: "nxv_" + "z" * 40}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "wrong_account"}
        assert entry.data[CONF_KEY] == KEY, "The old key must stay untouched."


class TestRemovingDevices:
    async def test_a_gone_instance_may_be_deleted(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Only what Nexview no longer has.

        Nothing is removed automatically, because an instance that vanished for
        a moment - somebody is editing settings - comes back with its history.
        But one taken out for good would otherwise sit in the list forever.
        """
        from custom_components.nexview import async_remove_config_entry_device

        await setup_entry(hass, entry)
        devices = dr.async_get(hass)

        sonarr = devices.async_get_device_by_identifier(
            (DOMAIN, f"{entry.entry_id}_sonarr-standard"), entry.entry_id
        )
        assert not await async_remove_config_entry_device(hass, entry, sonarr), (
            "Nexview still has this instance, so it must not be removable."
        )

        weg = devices.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{entry.entry_id}_sonarr-uhd")},
            name="Sonarr 4K",
        )
        assert await async_remove_config_entry_device(hass, entry, weg)

    async def test_nexview_itself_stays(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """Deleting the entry is how you get rid of Nexview, not deleting a device."""
        from custom_components.nexview import async_remove_config_entry_device

        await setup_entry(hass, entry)
        devices = dr.async_get(hass)
        main = devices.async_get_device_by_identifier(
            (DOMAIN, entry.entry_id), entry.entry_id
        )

        assert not await async_remove_config_entry_device(hass, entry, main)


class TestSayingSoWhenSomethingStops:
    async def test_a_lasting_outage_is_reported_once_and_its_return_too(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        nexview: AiohttpClientMocker,
        caplog,
    ) -> None:
        """⚠️ Once, not every thirty seconds.

        A log line repeated all night buries whatever else went wrong that
        night. But saying nothing at all leaves an entity unavailable with no
        explanation anywhere - so the first failure is a warning, and so is the
        recovery.
        """
        from custom_components.nexview.api import NexviewConnectionError

        await setup_entry(hass, entry)
        coordinator = entry.runtime_data

        with patch(
            "custom_components.nexview.api.NexviewClient.tile",
            AsyncMock(side_effect=NexviewConnectionError("no answer")),
        ):
            caplog.clear()
            await coordinator.async_refresh()
            erste = caplog.text.count("stopped answering")

            await coordinator.async_refresh()
            zweite = caplog.text.count("stopped answering")

        assert erste == 1, "The first failure has to be said out loud."
        assert zweite == 1, "The second one must not repeat it."

        caplog.clear()
        await coordinator.async_refresh()
        assert "answering for the dashboard again" in caplog.text, (
            "Coming back has to be reported too - that half is usually forgotten."
        )

class TestTheEventTable:
    """⚠️ Im Betrieb gefunden: eine Meldung landete als "other".

    Nexview meldet ueber den persoenlichen Rueckkanal sechsundzwanzig Arten,
    nicht die neun des Hausfunks - "Antwort auf dein Ticket", "dein
    vorgemerkter Titel ist da", "dein Kind wuenscht sich etwas". Fehlt eine in
    EVENT_ROUTING, faellt sie auf die Betriebs-Entitaet als ``other``, und wer
    darauf eine Automation bauen will, hat nichts, woran er sie festmachen
    kann.
    """

    def test_every_routed_type_is_declared(self) -> None:
        """Home Assistant feuert keinen Typ, den die Entitaet nicht kennt.

        Ohne diesen Abgleich waere ein Eintrag in EVENT_ROUTING wirkungslos -
        und zwar lautlos: Die Nachricht kaeme an, das Ereignis nicht.
        """
        from custom_components.nexview.const import EVENT_ROUTING, EVENT_TYPES

        fehlend = [
            f"{gruppe}/{typ}"
            for gruppe, typ in EVENT_ROUTING.values()
            if typ not in EVENT_TYPES.get(gruppe, [])
        ]
        assert fehlend == [], (
            f"Diese Ereignistypen werden zugeordnet, aber von ihrer Entitaet "
            f"nicht angemeldet: {fehlend}"
        )
        assert len(EVENT_ROUTING) >= 20, (
            f"Nur {len(EVENT_ROUTING)} Zuordnungen - das ist wieder der Stand "
            "vor dem persoenlichen Rueckkanal."
        )

    def test_every_declared_type_has_a_name_in_both_languages(self) -> None:
        """Ein Typ ohne Text steht als roher Bezeichner auf dem Bildschirm."""
        import json
        from pathlib import Path

        from custom_components.nexview.const import EVENT_TYPES

        basis = Path(__file__).parent.parent / "custom_components" / "nexview"
        geprueft = 0
        for datei in ("de.json", "en.json"):
            texte = json.loads((basis / "translations" / datei).read_text("utf-8"))
            for gruppe, typen in EVENT_TYPES.items():
                zustaende = texte["entity"]["event"][gruppe]["state_attributes"][
                    "event_type"
                ]["state"]
                for typ in typen:
                    assert typ in zustaende, f"{datei}: {gruppe}/{typ} hat keinen Text"
                    geprueft += 1
        assert geprueft > 40, f"Nur {geprueft} Texte geprueft - zu wenig."

class TestTheStorageSplit:
    """⚠️ Beim Durchsehen vermisst, und zu Recht.

    "Belegt durch die Bibliothek" wirft zwei sehr verschiedene Dinge zusammen:
    was die Bewohner angefragt haben und was dem Haus gehoert - alles, was
    schon vor Nexview da war oder nachtraeglich uebernommen wurde. Nur die
    erste Haelfte zaehlt gegen Kontingente und waechst, wenn jemand etwas
    anfragt.
    """

    async def test_house_and_people_add_up_to_the_total(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """Die Differenz, nicht eine zweite Abfrage.

        Zwei Zahlen aus derselben Summe koennen nicht auseinanderlaufen. Zwei
        getrennte Abfragen koennten es, und niemand merkte es.
        """
        from .conftest import TILE

        await setup_entry(hass, entry)

        gesamt = _wert(hass, entry, "used_space")
        haus = _wert(hass, entry, "house_space")
        leute = _wert(hass, entry, "people_space")

        assert None not in (gesamt, haus, leute)
        # Home Assistant rechnet in Terabyte um; verglichen wird deshalb mit
        # einer Toleranz statt auf Byte genau.
        assert abs((haus + leute) - gesamt) < 0.01, (
            f"Haus ({haus}) und Bewohner ({leute}) ergeben nicht die Summe ({gesamt})."
        )
        erwartet = TILE["bibliothek"]["hausbestand_bytes"] / 1_000_000_000_000
        assert abs(haus - erwartet) < 0.01

    async def test_an_older_nexview_puts_everything_on_the_people(
        self, hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock
    ) -> None:
        """Ein Nexview vor 0.31 kennt das Feld nicht.

        Dann ist der Hausbestand 0 und alles zaehlt bei den Bewohnern. Das ist
        die ehrlichere Vorgabe: Es sagt "wir wissen es nicht" durch eine Null
        beim Haus, statt eine erfundene Aufteilung zu zeigen.
        """
        from .conftest import (
            ABOUT,
            ANALYSIS,
            IDENTITY_ADMIN,
            MY_STORAGE,
            PLAYING,
            QUOTA,
            SERVERS,
            STATS,
            TILE,
        )

        alt = {**TILE, "bibliothek": {
            k: v for k, v in TILE["bibliothek"].items() if k != "hausbestand_bytes"
        }}
        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_ADMIN)
        aioclient_mock.get(f"{URL}/api/v1/dashboard", json=alt)
        aioclient_mock.get(
            f"{URL}/api/v1/admin/requests/pending/count", json={"pending": 0}
        )
        aioclient_mock.get(f"{URL}/api/v1/me/push", json={"eingerichtet": False})
        aioclient_mock.get(f"{URL}/api/admin/analyse", json=ANALYSIS)
        aioclient_mock.get(f"{URL}/api/admin/analyse/laufend", json=PLAYING)
        aioclient_mock.get(f"{URL}/api/admin/stats", json=STATS)
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
            f"{URL}/api/settings/qualitaetsprofile/medienserver", json=SERVERS
        )

        await setup_entry(hass, entry)

        assert _wert(hass, entry, "house_space") == 0
        assert _wert(hass, entry, "people_space") == _wert(hass, entry, "used_space")

    async def test_the_error_count_says_which_error(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Eine Zahl allein hilft niemandem.

        "Befunde, Fehler: 1" sagt, dass etwas nicht stimmt, und verschweigt
        was. Nexview liefert die dringendsten als Kennungen mit; Kennungen
        nennen keine Titel und keine Personen und duerfen deshalb in eine
        Datenbank, die alles jahrelang behaelt.
        """
        from .conftest import TILE

        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        eintrag = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_findings_error"
        )
        zustand = hass.states.get(eintrag)
        assert zustand.attributes.get("worst") == list(
            TILE["befunde"]["dringendste"]
        ), "Der Zaehler nennt nicht, worum es geht."

class TestWhatAnOperatorDoesNotGet:
    """⚠️ Beim Durchsehen aufgefallen: beim Betreiber ist das immer null.

    Er hatte recht, und Nexviews Quelltext sagt es woertlich: Was ein
    Administrator holt, gehoert dem Haus. Ihm etwas zuzurechnen erfuellte
    keinen Zweck und verfaelschte die Uebersicht - dort staende dann "admin
    belegt 20 TB" und alle anderen waeren daneben unsichtbar.

    Damit stehen bei ihm drei Zahlen dauerhaft auf null, und zwar nicht, weil
    er nichts getan hat, sondern weil es woanders gebucht wird. Eine Null, die
    nichts bedeutet, ist schlechter als kein Eintrag.
    """

    async def test_an_operator_gets_no_personal_storage_figures(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        for unique in ("my_storage_used", "my_items"):
            assert (
                registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{entry.entry_id}_{unique}"
                )
                is None
            ), f"{unique} steht beim Betreiber und ist dort immer null."

    async def test_an_operator_gets_no_quota_figures_either(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """Kein Kontingent, also auch kein Verbrauch und keine Restmenge."""
        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        for unique in (
            "my_movie_quota_used",
            "my_movie_quota_remaining",
            "my_series_quota_used",
            "my_series_quota_remaining",
            "my_storage_remaining",
        ):
            assert (
                registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{entry.entry_id}_{unique}"
                )
                is None
            ), f"{unique} steht beim Betreiber, der gar kein Kontingent hat."

    async def test_but_the_bell_and_the_tickets_stay(
        self, hass: HomeAssistant, entry: MockConfigEntry, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ Die Gegenprobe, damit hier nicht zu viel verschwindet.

        Ungelesene Meldungen und eigene Tickets haengen an keinem Kontingent
        und an keiner Zurechnung. Sie gelten fuer jeden, auch fuer den
        Betreiber - und ohne sie bliebe von einem persoenlichen Zugang wieder
        fast nichts uebrig.
        """
        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        assert registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_my_unread"
        ), "Die Glocke fehlt."
        assert registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_my_open_tickets"
        ), "Die eigenen Tickets fehlen."

    async def test_a_user_keeps_everything(
        self, hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock
    ) -> None:
        """Bei einem begrenzten Konto bleibt jede Zahl stehen."""
        from .conftest import ABOUT, IDENTITY_USER

        aioclient_mock.get(f"{URL}/api/v1/me", json=IDENTITY_USER)
        aioclient_mock.get(f"{URL}/api/v1/me/push", json={"eingerichtet": False})
        aioclient_mock.get(f"{URL}/api/v1/about", json=ABOUT)
        aioclient_mock.get(
            f"{URL}/api/v1/requests/quota",
            json={
                "movie": {"used": 2, "limit": 5},
                "tv": {"used": 1, "limit": 3},
            },
        )
        aioclient_mock.get(
            f"{URL}/api/v1/storage/me",
            json={
                "used_bytes": 900_000_000,
                "items": 4,
                "limit_bytes": 5_000_000_000,
                "zurechenbar": True,
            },
        )
        aioclient_mock.get(
            f"{URL}/api/v1/notifications/unread/count", json={"unread": 0}
        )
        aioclient_mock.get(f"{URL}/api/v1/tickets/open-count", json={"count": 0})

        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        geprueft = 0
        for unique in (
            "my_movie_quota_used",
            "my_movie_quota_remaining",
            "my_series_quota_used",
            "my_storage_used",
            "my_storage_remaining",
            "my_items",
        ):
            assert registry.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_{unique}"
            ), f"{unique} fehlt bei einem Konto mit Grenze."
            geprueft += 1
        assert geprueft == 6

class TestWhatTheAccountDeviceWasMissing:
    """Vier Luecken, die beim Durchsehen eines Konten-Geraets auffielen."""

    def _entry(self) -> MockConfigEntry:
        from custom_components.nexview.const import CONF_ACCOUNTS

        return MockConfigEntry(
            domain=DOMAIN,
            unique_id=f"{URL}::1",
            data={"url": URL, "api_key": KEY, "webhook_id": WEBHOOK_ID},
            options={CONF_ACCOUNTS: ["7"]},
        )

    async def test_every_icon_exists(self, hass: HomeAssistant) -> None:
        """⚠️ Ein erfundenes Symbol bleibt einfach leer.

        "Serien uebrig" trug ``mdi:television-plus``, und das gibt es nicht -
        MDI kennt television-play, -classic, -guide und neun weitere, aber
        kein -plus. Home Assistant meldet das nicht, es zeigt nichts an.

        Geprueft wird gegen die Symbolliste, die im Frontend dieser
        Installation liegt. Damit faellt der Test um, sobald jemand einen
        Namen erfindet - und nicht erst, wenn es jemandem auffaellt.
        """
        import json
        from pathlib import Path

        kandidaten = list(Path("/opt/hatest").rglob("hass_frontend/static/mdi"))
        if not kandidaten:
            import homeassistant.components.frontend as hf

            kandidaten = list(Path(hf.__file__).parent.rglob("static/mdi"))
        if not kandidaten:
            import pytest

            pytest.skip("Symbolliste dieser Installation nicht gefunden")

        bekannt: set[str] = set()
        for datei in kandidaten[0].glob("*.json"):
            try:
                inhalt = json.loads(datei.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(inhalt, dict):
                bekannt.update(inhalt)
        assert len(bekannt) > 5000, f"Nur {len(bekannt)} Symbole gelesen - zu wenig."

        eigene = json.loads(
            (
                Path(__file__).parent.parent
                / "custom_components/nexview/icons.json"
            ).read_text(encoding="utf-8")
        )
        geprueft = 0
        for bereich, eintraege in eigene.get("entity", {}).items():
            for schluessel, wert in eintraege.items():
                name = (wert or {}).get("default", "")
                if not name.startswith("mdi:"):
                    continue
                geprueft += 1
                assert name[4:] in bekannt, (
                    f"{bereich}.{schluessel} nennt {name}, und das Symbol gibt es nicht."
                )
        assert geprueft > 40, f"Nur {geprueft} Symbole geprueft - zu wenig."

    async def test_the_allowance_itself_is_a_figure(
        self, hass: HomeAssistant, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ "verbraucht 2" und "uebrig 8" nennen die Grenze nur zusammen.

        Auf einer Kachel steht meist eine der beiden, und dann fehlt der
        Massstab. Die Grenze selbst gehoert daneben.
        """
        entry = self._entry()
        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        for unique, erwartet in (
            ("account7_movie_quota_limit", "5"),
            ("account7_series_quota_limit", "3"),
        ):
            kennung = registry.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_{unique}"
            )
            assert kennung, f"{unique} fehlt."
            assert hass.states.get(kennung).state == erwartet

    async def test_exhausted_says_which_half(
        self, hass: HomeAssistant, nexview: AiohttpClientMocker
    ) -> None:
        """⚠️ "Aufgebraucht" ohne "woran" ist eine Sackgasse.

        Wer noch Platz hat, aber keine Stueck mehr, braucht eine andere
        Antwort als wer sein Speicherkontingent voll hat. Der Zustand allein
        unterscheidet das nicht.
        """
        entry = self._entry()
        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        kennung = registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{entry.entry_id}_account7_quota_exhausted"
        )
        zustand = hass.states.get(kennung)
        assert zustand.state == "on"
        assert zustand.attributes.get("exhausted") == ["series"], (
            "Das Gast-Konto hat drei von drei Serien und sonst Platz - genau "
            "der Fall, den der Zustand allein verschweigt."
        )

    async def test_the_last_sign_in_is_a_timestamp(
        self, hass: HomeAssistant, nexview: AiohttpClientMocker
    ) -> None:
        """Ein Konto, das seit einem Jahr niemand angefasst hat, ist die
        haeufigste Frage vor dem Aufraeumen."""
        entry = self._entry()
        await setup_entry(hass, entry)

        registry = er.async_get(hass)
        kennung = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_account7_last_login"
        )
        assert kennung, "Der letzte Login fehlt."
        zustand = hass.states.get(kennung)
        assert zustand.state.startswith("2026-09-01T18:30:00"), zustand.state
        assert "+00:00" in zustand.state, (
            "Nexview schreibt ohne Zonenangabe; ohne UTC daran lehnt Home "
            "Assistant den Zeitstempel ab."
        )
