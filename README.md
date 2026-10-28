# Nachrichtenlage

Ein persönliches News-Dashboard, das sich selbst aktualisiert. Der Schwerpunkt liegt auf Wirtschaft, Finanzmärkten, Notenbanken und Quartalszahlen. Auf einem Bildschirm siehst du alles auf einen Blick:

- **Oben links, Themenvorschläge:** 5 Post-Ideen mit fertiger Überschrift und Subline. Ein Klick auf „Kopieren“ übernimmt beides, ein Klick auf den Vorschlag zeigt Begründung und Quellen.
- **Oben Mitte, Wichtigste Meldungen:** die Top-Meldungen des Tages.
- **Oben rechts, Quartalszahlen:** die Termine der nächsten 14 Tage.
- **Unten, fünf Spalten:** alle Meldungen nach Märkte, Konjunktur, Notenbanken, International und weitere News.

Jeder Bereich scrollt einzeln, die Seite selbst bleibt stehen. In der Kopfzeile filterst du nach Kategorie, Zeitraum und Stichwort und blendest die Sublines ein oder aus. Rechts oben steht, wie viele Meldungen seit deinem letzten Besuch neu sind. Auf kleinen Bildschirmen und am Handy stehen die Bereiche untereinander.

GitHub holt alle 30 Minuten (ca. 5 bis 22 Uhr) die neuesten Meldungen ab und veröffentlicht die Seite neu. Danach ist kein weiterer Eingriff nötig.

## Was im Ordner liegt

| Datei | Wofür |
|---|---|
| `feeds.json` | Die Liste der Nachrichtenquellen |
| `termine.json` | Feste Termine für Quartalszahlen (für November bereits ausgefüllt) |
| `build.py` | Ruft die Quellen ab und baut die Seite. Muss nicht angepasst werden. |
| `template.html` | Aussehen der Seite |
| `update.yml` | Zeitplan für die automatische Aktualisierung (siehe Schritt 4) |

## Einrichtung (ca. 20 Minuten, einmalig)

1. **GitHub-Konto anlegen** auf github.com, falls noch keins vorhanden ist.
2. **Neues Repository erstellen:** oben rechts auf „+“ und dann „New repository“. Als Namen zum Beispiel `nachrichtenlage` eingeben, „Public“ wählen und auf „Create repository“ klicken.
3. **Dateien hochladen:** Klicke auf „uploading an existing file“. Ziehe `feeds.json`, `termine.json`, `build.py`, `template.html`, `README.md` und `.gitignore` hinein und klicke auf „Commit changes“.
4. **Zeitplan anlegen:** Klicke auf „Add file“ und dann „Create new file“. Als Dateinamen tippst du genau `.github/workflows/update.yml` ein. Kopiere den Inhalt der Datei `update.yml` aus diesem Paket hinein und klicke auf „Commit changes“.
5. **API-Schlüssel hinterlegen** (für Themenvorschläge und Termin-Recherche): Erstelle auf console.anthropic.com einen API-Schlüssel und lade etwas Guthaben auf. Gehe dann im Repository zu „Settings“, „Secrets and variables“ und „Actions“. Klicke auf „New repository secret“, gib als Namen `ANTHROPIC_API_KEY` ein und füge den Schlüssel als Wert ein.
6. **Veröffentlichung einschalten:** Gehe zu „Settings“ und dann „Pages“. Wähle unter „Source“ den Eintrag „GitHub Actions“.
7. **Erster Start:** Gehe zum Reiter „Actions“ und wähle links „Nachrichtenlage aktualisieren“. Klicke dann auf „Run workflow“. Der erste Lauf dauert wegen der Termin-Recherche ein bis drei Minuten.
8. **Seite öffnen:** Die Adresse lautet `https://DEIN-GITHUB-NAME.github.io/nachrichtenlage/`. Am besten als Lesezeichen speichern.

## Kosten

GitHub ist kostenlos. Für Claude fallen Kosten pro Nutzung an:

- Themenvorschläge und Top-Meldungen: etwa 6 Durchläufe pro Tag mit einem kleinen, günstigen Modell
- Termin-Recherche: ein Durchlauf pro Tag mit Websuche, ebenfalls mit dem günstigen Modell

Die genauen Kosten siehst du auf console.anthropic.com. Dort kannst du auch ein monatliches Limit setzen, das empfehle ich. Ohne Schlüssel läuft die Seite trotzdem: Dann fehlen die Themenvorschläge und die automatische Termin-Recherche. „Heute im Fokus“ zeigt dann die Themen, über die die meisten Quellen berichten.

Zusammen sind das voraussichtlich nur wenige Euro im Monat.

## Termine pflegen

Feste Termine stehen in `termine.json`. Diese Einträge haben Vorrang vor der automatischen Recherche, außer ein fester Termin ist als unbestätigt markiert und Claude findet einen bestätigten. Vergangene Termine blendet die Seite automatisch aus. Für Dezember musst du nichts eintragen, die tägliche Recherche ergänzt die Termine. Für wichtige Termine lohnt sich trotzdem ein fester Eintrag.

Recherchierte Termine können Fehler enthalten. Unbestätigte stehen kursiv. Prüfe einen Termin vor einem Post kurz auf der Investor-Relations-Seite des Unternehmens.

## Quellen ändern

Öffne `feeds.json` im Repository und klicke auf das Stift-Symbol. Jede Quelle hat einen Namen, die Adresse ihres RSS-Feeds und eine Kategorie: `maerkte`, `konjunktur`, `notenbanken`, `international` oder `allgemein`. Nach dem Speichern greift die Änderung bei der nächsten Aktualisierung.

Unten auf der Seite steht unter „Quellen im Detail“, welche Quellen erreichbar sind. Ist eine Quelle dauerhaft nicht erreichbar, hat sich meist die Feed-Adresse geändert.

## Gut zu wissen

- **Vorschläge sind Entwürfe:** Claude nutzt nur die Überschriften und Teaser aus den Feeds und ist angewiesen, keine Anlageempfehlungen zu formulieren. Fakten und Zahlen vor dem Posten trotzdem an der Quelle prüfen.
- **Zeitplan:** GitHub startet geplante Läufe manchmal mit einigen Minuten Verspätung. Das ist normal.
- **Pausen:** Gibt es 60 Tage lang keine Änderung im Repository, pausiert GitHub den Zeitplan und schickt eine E-Mail. Dann reicht ein Klick auf „Enable workflow“ im Reiter „Actions“.
- **Sichtbarkeit:** Die Seite ist nicht in Suchmaschinen gelistet, aber jeder mit dem Link kann sie öffnen. Manche Verlage erlauben ihre Feeds nur für den persönlichen Gebrauch, deshalb ist die Seite als persönliches Werkzeug gedacht und nicht zum Weiterverbreiten.
- **Lokal testen:** Mit installiertem Python reicht `python build.py`. Danach liegt die Seite unter `site/index.html`.
