# Das Symbol der Integration

Home Assistant nimmt es von hier. **Kein Eintrag bei `home-assistant/brands`
nötig** und auch nicht mehr möglich: Seit 2026.3 bringen Anbindungen ihr Symbol
selbst mit, und lokale Dateien haben Vorrang vor dem, was der zentrale Dienst
liefert. Ein Pull Request dorthin wird seither abgelehnt.

| Datei | Größe | wofür |
|---|---|---|
| `icon.png` | 256×256 | überall: Integrationsliste, Geräte, Suche |
| `icon@2x.png` | 512×512 | für Bildschirme mit hoher Auflösung |

Home Assistant nimmt das Icon auch dort, wo eine Wortmarke stünde. Ein eigenes
`logo.png` (querformatig, mit Schriftzug) wäre möglich, aber nichts fehlt ohne
es. Für den hellen und den dunklen Modus getrennte Fassungen gäbe es als
`dark_icon.png`; dieses Symbol trägt beide.

## Woher sie kommen

Beide entstehen aus einer Vorlage, dem App-Symbol der Projektseite
(`nexapps-website/public/assets/img/icon-512.png`). **Eine Vorlage, zwei
Größen** — wer zwei Zeichnungen pflegt, hat irgendwann zwei verschiedene
Symbole, und beim Wechsel der Auflösung springt es.

Zum Nachziehen, wenn sich die Vorlage ändert:

```python
from PIL import Image

bild = Image.open("icon-512.png").convert("RGBA")
bild = bild.crop(bild.getbbox())          # durchsichtigen Rand weg
for name, kante in (("icon.png", 256), ("icon@2x.png", 512)):
    bild.resize((kante, kante), Image.LANCZOS).save(name, optimize=True)
```
