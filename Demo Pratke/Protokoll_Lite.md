# Protokoll: Stresstests und Grenzfälle der Lite-Version

Stand 09.11.2026, Branch `gurobi`. Nichts davon ist committet. Alle Läufe mit Gurobi und der festen Rechenzeit von 20 s, nacheinander in einem Prozess (eine Lizenzsitzung).

## Behobene Kleinigkeiten

| # | Problem | Behebung | Dateien |
|---|---|---|---|
| 1 | **Oktober wurde immer abgelehnt** („Arbeitszeit und Pausen“): Die Nachtschicht in der Nacht der Zeitumstellung dauert eine Stunde länger, also über 10 h Arbeit und über 6 h am Stück. | Das MILP schließt Schichten, die an einem Tag schon für sich gegen die Arbeitszeitregeln verstoßen, von vornherein aus, wie es das CP-SAT-Modell schon tat. Folge: In der Zeitumstellungsnacht bleibt der Nachtdienst als Lücke offen, wegen Sa = So auch am Sonntag (2 Lücken pro Oktober). | `api/app/solver/milp/service.py`, `model.tex` (Menge N^A) |
| 2 | Verstöße erschienen auf der Prüfseite **auf Englisch** („Balance -924 minutes … is outside ±460“). | Je Regel ein kurzer deutscher Text, beim Monatskonto mit dem Saldo der Person, z. B. „Monatskonto: Saldo −154:00 h, erlaubt sind ±7:40 h · Schulz Peter“. | `webapp/src/app/review/review-summary.tsx` |
| 3 | „Nur bestimmte Schichten“ ohne Schicht und „Wunschschicht/Schicht frei“ ohne Schicht ließen sich speichern und ergaben eine Fehlermeldung. | Der Speichern-Knopf bleibt gesperrt, bis eine Schicht gewählt ist; ein Hinweis sagt, was fehlt. | `webapp/src/app/availability/availability-calendar.tsx` |
| 4 | **Gespeicherte Pläne der Vollversion** (z. B. `Demo Pratke/Plan 1–4`, Stationen PE 83 usw.) ließen sich laden, wurden aber nie angezeigt. Die Prüfseite zeigte „Dienstplan für einen anderen Monat“, und der Link führte im Kreis. | Die Prüfseite vergleicht nur noch den Monat. Die alten Demo-Pläne lassen sich jetzt in der Lite-Version laden und ansehen (geprüft mit Plan 4). | `webapp/src/app/review/page.tsx` |
| 5 | Wählbare Jahre 2025–2028, aber nur 2026/2027 geprüft. | Jahresauswahl nur noch 2026 und 2027; andere Monate in der URL werden auf den Standardmonat umgeleitet. | `webapp/src/lib/selection.ts`, `scope.ts`, `planning-scope-picker.tsx`, README, Betriebsanleitung |
| 6 | Unsortierte Importliste (ruff I001) | sortiert | `api/app/solver/milp/service.py` |

## Was geprüft wurde und funktioniert

- **Einträge über die API, so wie die Webapp sie schreibt** (Januar 2027): Urlaub, „nicht verfügbar“, freier Tag, „nur N“ an drei Tagen, Urlaub am 01.02. und vier Wünsche. Ein vorbelegter Eintrag wurde gelöscht.
  - Alles steht im Kalender und wird eingehalten: frei bzw. nur N, keine Nacht am 31.01. vor dem Urlaub.
  - Gutschriften stimmen: 7 Urlaubstage ergeben 3234 min, nach dem Löschen der Fortbildung 0.
  - 5 von 6 Wünschen sind erfüllt. Der sechste („Frühdienst frei“ für die einzige Hilfskraft) ist zu Recht nicht erfüllt, weil sie für den Hilfskraft-Bedarf gebraucht wird.
- **Grenzfälle der Eingaben:** kein Absturz, keine Überschreitung der 20 s. Getestet wurden:
  - Mindestbesetzung komplett 0, nur Zwischendienst, nur die Feiertagszeile, Nächte 5
  - Urlaub einen ganzen Monat, Hilfskraft nie verfügbar, Azubi nur Nacht erlaubt
  - Wunschtag bzw. Freiwunsch an jedem Tag, alle Fachkräfte eine Woche Urlaub
  - viele Einträge in einem Monat, der an einem Sonntag beginnt
- **HTTP und Oberfläche:**
  - Monate außerhalb 2026/2027 oder ungültige Monate in der URL leiten um.
  - CSV-Dateien und Pfadtricks liefern 404; die Veröffentlichung liefert 404.
  - Ungültige Einträge (unbekannter Mitarbeiter, unbekannte Schicht, Bedarf 6, andere Station) lehnt die API mit 422 ab; die Webapp zeigt dazu deutsche Texte.
  - Fehlerhafte Importe (leere Datei, vertauschte Dateien, veränderte input.json) werden erkannt und deutsch gemeldet.
- **Lizenzfehler:** Ohne gültige Lizenz endet die Berechnung als „Berechnung nicht möglich“ mit Hinweis auf das WLAN; der nächste Versuch öffnet eine frische Sitzung.
- **Rechenzeit:** In allen Stresstests liefern 20 s und 60 s dieselben Lücken, Salden und Wünsche. Nur die beiden letzten Stufen (Schichtverteilung, gleiche Folgeschicht) unterscheiden sich minimal.

- **Doppelter Start einer Berechnung:** Der zweite Start wird abgelehnt (423; die Webapp sagt „Es wird bereits ein Dienstplan berechnet …“). Nach dem Ende startet eine neue Berechnung normal und nutzt dieselbe Lizenzsitzung.

## Offene Fragen für morgen

### 1. Modelländerungen A–D (Patch liegt bereit, nicht angewendet)

`Demo Pratke/Vorschlag_Modell_A-D.patch` ändert nur `api/app/solver/milp/service.py`. Anwenden mit `git apply "Demo Pratke/Vorschlag_Modell_A-D.patch"`. Jeder Teil ist im Code kommentiert und lässt sich einzeln wieder herausnehmen.

- **A Ersatzruhetag als harte Regel:** Jeder gearbeitete Sonn- oder Feiertag bekommt einen eigenen freien Werktag im Fenster, genau wie der Check es prüft. *Ohne A wurden Juni 2026 und Oktober 2027 mit Standardeingaben abgelehnt.*
- **B 11-h-Ruhezeit als harte Regel:** Sie wird aus den echten Dienstzeiten jedes Schichtpaars abgeleitet (bei uns nur S → F). *Ohne B wurde „viele Einträge“ im November 2026 abgelehnt.* Die Stufe `Min_L_to_E` endet dann immer bei 0 und könnte entfallen.
- **C Sa = So am Monatsanfang nur, wenn der Samstag davor gearbeitet wurde.** *Ohne C fallen in jedem Monat, der an einem Sonntag beginnt, alle 4 Fachkraft-Dienste des 1. als Lücke aus* (Feb., März, Nov. 2026, Aug. 2027), weil die erfundenen Vortage frei sind. Inhaltlich erlaubt C über den Monatswechsel ein „halbes Wochenende“, wenn der Samstag vorher frei war.
- **D Stufen „Lücken“ und „Saldo“ exakt statt mit 3 % relativer Optimalitätslücke.** Bei großen Stufenwerten ließ der Spielraum vermeidbare Lücken bzw. Salden durch. *Ohne D:* „Bedarf überall 5“ hatte 646 statt 635 Lücken; bei „Hilfskraft nie verfügbar“ lagen 3 statt 1 Person außerhalb des Saldo-Bands.

Gemessen (24 Standardmonate 2026/2027 + 7 Stresstests, je 20 s):

| | unverändert | nur D | A+B+C+D |
|---|---|---|---|
| Standardmonate angenommen | 22 von 24 | 23 von 24 | **24 von 24** |
| Monate mit Lücken (ohne Oktober) | 4 (je 4 Lücken) | 4 | **0** |
| „viele Einträge“ Nov. 2026 | abgelehnt (Ruhezeit) | abgelehnt | **angenommen** |
| „Hilfskraft nie verfügbar“: Personen außerhalb des Saldos | 3 | **1** | 1 |
| „Bedarf überall 5“: Lücken | 646 | **635** | 635 |
| Laufzeit | ≤ 20,3 s | ≤ 20,2 s | ≤ 20,4 s |

**Meine Empfehlung:** alle vier anwenden. A und B sind mein früherer Punkt 3, den du zurückgestellt hattest; die Daten zeigen, dass beide in normalen Monaten zu „Regelverstößen“ führen. Wenn du zustimmst, passe ich `model.tex`, `model_lite.tex` und die Liste „Berücksichtigt“ mit an. A und D gehören auch in `gurobi_full`, ebenso der Oktober-Fix (Nr. 1 oben).

### 2. „Regelverstöße · Monatskonto“, wenn jemand sein Soll gar nicht erreichen kann

Das bleibt auch mit A–D, und zwar in diesen Fällen:

- viele „nicht verfügbar“-Tage, die anders als Urlaub nicht gutgeschrieben werden
- eine Qualifikation ohne jeden Bedarf, etwa Azubis auf 0
- Bedarf weit über der Kapazität: Weil Lücken vor dem Saldo kommen, arbeiten dann alle Überstunden

Inhaltlich stimmt die Meldung, in der Demo wirkt sie aber wie ein Fehler („Der Plan ist nicht verwendbar“). Möglichkeiten:

- (a) so lassen und in der Demo erklären,
- (b) reine Saldo-Verstöße gelb als Hinweis zeigen statt rot als „nicht verwendbar“,
- (c) „nicht verfügbar“ wie einen freien Tag behandeln, also mit Hinweis, dass das Soll dann nicht erreichbar ist.

Das ist eine inhaltliche Entscheidung für dich.

### 3. Oktober: 2 Lücken in der Nacht der Zeitumstellung

Die Nacht ist nach Arbeitszeitgesetz mit unserer Nachtschicht nicht besetzbar (über 10 h). Wegen Sa = So fällt auch die Sonntagsnacht weg. Lösbar wäre das nur mit einer eigenen, kürzeren Nachtschicht für diese Nacht. Ich würde es so lassen und in der Demo erklären.

### 4. Kleinere Punkte

- **Speichern als eine Datei** statt input.json + result.json, damit Paare nicht vertauscht werden (Vorschlag von gestern). Die Betriebsanleitung empfiehlt bis dahin einen Ordner je Plan.
- **Die Playwright-Browsertests** beschreiben noch die Vollversion und sind nicht angepasst (die CI läuft nur auf `main`). Ebenso beschreibt die mkdocs-Doku unter `docs/` die Vollversion; die README hat einen Abschnitt zur Demo-Version.
- **Ruhezustand:** Ich habe `caffeinate` laufen lassen, damit der Mac während der Tests nicht einschläft; es endet von selbst.
