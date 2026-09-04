# Für Home Assistants `brands`-Repository

Ohne einen Eintrag dort zeigt Home Assistant ein graues Feld statt eines
Symbols, und zwar überall: in der Integrationsliste, auf jedem Gerät, in der
Suche beim Hinzufügen.

Die beiden Dateien hier sind, was dort hingehört:

| Datei | Größe | wohin |
|---|---|---|
| `icon.png` | 256×256 | `custom_integrations/nexview/icon.png` |
| `icon@2x.png` | 512×512 | `custom_integrations/nexview/icon@2x.png` |

Beide entstehen aus einer Vorlage, dem App-Symbol der Projektseite
(`nexapps-website/public/assets/img/icon-512.png`), erzeugt mit dem Skript, das
in der Beschreibung dieses Ordners steht. **Eine Vorlage, zwei Größen** — wer
zwei Zeichnungen pflegt, hat irgendwann zwei verschiedene Symbole, und beim
Wechsel der Auflösung springt es.

## So kommen sie dorthin

`brands` gehört Home Assistant, nicht diesem Projekt. Der Weg ist ein Pull
Request:

1. `home-assistant/brands` abzweigen.
2. `custom_integrations/nexview/` anlegen und beide Dateien hineinlegen.
3. Pull Request stellen. Geprüft wird maschinell: quadratisch, PNG mit
   Alphakanal, genau diese beiden Größen, kein unnötiger durchsichtiger Rand.

⚠️ **Erst sinnvoll, wenn die Integration öffentlich ist.** Ein Pull Request für
etwas, das niemand installieren kann, wird zu Recht abgelehnt.
