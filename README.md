# AutoISO-DxOPureRaw

Ein kleines Windows-Tool, das in einem Ordner alle RAW-Dateien über einem einstellbaren ISO-Wert heraussucht und an **DxO PureRAW 5** übergibt. So landen nur die rauschanfälligen High-ISO-Bilder in der Entrauschung.

## Funktionen

- Liest den ISO-Wert direkt aus den RAW-Dateien. Dafür braucht es keine Zusatzprogramme und keine Python-Pakete.
- Unterstützte Formate: CR2, CR3, CRW, NEF, NRW, ARW, SRF, SR2, DNG, ORF, RW2, RAF, PEF, SRW, 3FR, IIQ, ERF, MEF, MOS, RWL, KDC und DCR.
- Frei einstellbarer ISO-Grenzwert, wahlweise „größer als“ oder „größer oder gleich“.
- Unterordner lassen sich optional einbeziehen.
- Bilder mit einer vorhandenen PureRAW-Ausgabe (`…_DxO…`, auch im Unterordner `DxO`) werden übersprungen.
- In der Trefferliste lassen sich einzelne Dateien von Hand an- oder abwählen.
- Drei Übergabe-Modi, die denen im Lightroom-Menü von DxO entsprechen:
  - **Mit Vorschau**: PureRAW öffnet sich mit den Bildern, die Einstellungen wählst du dort.
  - **Sofort verarbeiten**
  - **Sofort mit zuletzt verwendeten Einstellungen**
- Grafische Oberfläche und Kommandozeilenmodus.
- Die Einstellungen werden in `settings.json` gespeichert.

## Voraussetzungen

- Windows
- Python 3.10 oder neuer, mit tkinter (bei der Standardinstallation von python.org enthalten)
- DxO PureRAW 5. Das Tool findet es automatisch unter `C:\Program Files\DxO\`, der Pfad lässt sich aber auch von Hand angeben.

## Benutzung

### Oberfläche

Doppelklick auf `Auto ISO DxO PureRaw.bat`, alternativ:

```powershell
python auto_iso_dxo_pureraw.py
```

1. Ordner wählen und den ISO-Grenzwert einstellen.
2. Auf **Scannen** klicken. Die Treffer sind danach angehakt. Ein Klick in die ✔-Spalte, ein Doppelklick oder die Leertaste schaltet einzelne Dateien um.
3. Auf **An PureRAW senden** klicken.

### Kommandozeile

```powershell
python auto_iso_dxo_pureraw.py --folder "D:\Fotos\Konzert" --iso 3200 --dry-run
```

| Option | Bedeutung |
|---|---|
| `--folder` | Ordner mit den RAW-Dateien (Pflicht) |
| `--iso` | ISO-Grenzwert |
| `--inclusive` | den Grenzwert selbst einschließen (`>=` statt `>`) |
| `--recursive` | Unterordner einbeziehen |
| `--include-processed` | bereits verarbeitete Bilder nicht überspringen |
| `--mode preview\|instant\|last` | Übergabe-Modus (siehe oben) |
| `--pureraw` | Pfad zur `PureRAWv5.exe` |
| `--dry-run` | nur auflisten, nichts an PureRAW senden |

Werte, die nicht angegeben werden, kommen aus `settings.json`.

## Wie die Übergabe an PureRAW funktioniert

PureRAW 5 ignoriert Bildpfade, die direkt auf der Kommandozeile stehen. Das Tool macht es deshalb wie DxOs eigenes Lightroom-Plugin: Es schreibt die Dateien in eine temporäre Liste und startet PureRAW im Plugin-Modus.

```
PureRAWv5.exe --as-lightroom-preview-plugin --lr-version=14.0 --batch-file <liste.txt>
```

Der Modus-Schalter übernimmt das nächste Argument als seinen Wert, deshalb muss `--lr-version` direkt danach stehen. PureRAW löscht die Liste nach dem Einlesen selbst.

## Hinweise

- Getestet ist das Tool mit PureRAW 5. Der Modus „Mit Vorschau“ ist geprüft, die beiden Sofort-Modi noch nicht.
- Erscheint bei einer Kamera „ISO nicht lesbar“, kennt der eingebaute EXIF-Leser das Format noch nicht. Ein Issue mit Kameramodell und, wenn möglich, einer Beispieldatei hilft weiter.

## Dateien

| Datei | Inhalt |
|---|---|
| `auto_iso_dxo_pureraw.py` | Oberfläche, Kommandozeile und Übergabe an PureRAW |
| `exif_iso.py` | abhängigkeitsfreier ISO-Leser für RAW-Dateien |
| `Auto ISO DxO PureRaw.bat` | startet die Oberfläche ohne Konsolenfenster |
