# Auftrag: 25-minütige Demo-Simulation des Schichtplan Managers

Du bist **Laptop N von 5** (die Nummer steht in der Nachricht, mit der du gestartet wurdest). Auf allen fünf
Laptops läuft gleichzeitig dieselbe Simulation, jeweils mit anderen Monaten. Du arbeitest allein auf diesem
Laptop und gibst am Ende einen Bericht ab.

## Worum es geht

Der **Schichtplan Manager** ist ein Prototyp des Lehrstuhls für Kombinatorische Optimierung (RWTH Aachen). Er
erstellt den Dienstplan einer Krankenhausstation für einen Monat. Die Demo-Version („Lite“) wird bald auf einer
Messe bzw. beim Praxispartner (St. Marien-Hospital Düren) gezeigt. Besucher (Pflegedienstleitungen, Ärztinnen,
Stationsleitungen, IT-Leute) probieren ihn etwa 20 Minuten lang an einem Laptop aus. Der Prototyp soll
**idiotensicher** sein: keine Abstürze, keine provozierbaren Fehler, in 30 Sekunden ein plausibler Plan.

Deine Aufgabe: **Spiele 25 Minuten lang solche Besucher** und mache Eingaben, wie sie über die Oberfläche möglich
sind. Überwiegend sinnvoll, teils leicht zufällig, vereinzelt grenzwertig. Melde alles, was schiefgeht oder einer
Pflegedienstleitung seltsam vorkäme.

## Die App in Kürze

- Läuft lokal in Docker: API (FastAPI, `http://127.0.0.1:8000`) und Webapp (Next.js, `http://localhost:3000`).
  Der Solver ist Gurobi; er braucht Internet für seine Lizenz.
- Eine fiktive **Musterstation** mit 12 Personen: IDs 1–9 Fachkräfte (7, 8, 9 in Teilzeit 80/85/90 %),
  10 Hilfskraft, 11 und 12 Azubis. Monate: nur **2026 und 2027**.
- Schichten: Früh F 05:55–13:25 (7:00 h), Zwischen Z 08:30–14:15 (5:45 h), Spät S 13:15–21:00 (7:15 h),
  Nacht N 20:10–06:10 (9:15 h). Soll: 38,5 h/Woche, Teilzeit anteilig.
- Vorgabe Mindestbesetzung je Monat: werktags Fachkraft F3/S2/N1, Hilfskraft F1, Azubi F1/S1; Wochenende und
  Feiertag Fachkraft F2/S1/N1. Jeder Monat startet mit Beispieleinträgen (eine Urlaubswoche, ein Fortbildungstag,
  zwei Wünsche).
- **Feste Regeln:** ein Dienst pro Tag; Einschränkungen gelten immer; keine Nacht vor einem Abwesenheitstag, kein
  Spätdienst vor Urlaub oder Fortbildung; höchstens 10 Arbeitstage am Stück (Fortbildung zählt mit); Nächte in
  Blöcken von 2–3, danach 2 Tage ganz frei (auch ohne Fortbildung), am 3. Tag kein Frühdienst, 7 Tage zwischen
  Blöcken; Wochenende: Samstag und Sonntag gleiche Schicht oder beide frei, nie zwei Wochenenden in Folge. Endet ein
  Monat an einem Samstag, wird der Sonntag unsichtbar mitgeplant. Früh/Spät darf jede Qualifikation, Nacht und
  Zwischen nur bei eigenem Bedarf im Monat.
- **Ziele in Rangfolge:** 1 Saldo je Person innerhalb **±5 h** · 2 Wochenende über den Monatswechsel fortführen
  (nur mit Vormonat) · 3 wenige Lücken · 4 Lücken verteilen · 5 Tage gleichmäßig besetzen · 6 Samstage je
  Qualifikation gleich verteilen · 7 Wünsche · 8 Rotation (jede Schichtart in jedem 28-Tage-Fenster) ·
  9 Schichten gleichmäßig · 10 wenige Spät→Früh-Wechsel · 11 gleiche Schicht wie am Vortag (`cons`).
  Rechenzeit fest 30 s.
- Danach prüft ein **unabhängiges Prüfprogramm** den Plan: *angenommen* oder *abgelehnt* (mit Regel, Person,
  Datum). Spät→Früh ist erlaubt und wird nur gezählt.

## Vorbereitung (2–3 Minuten)

1. Arbeitsverzeichnis ist das Repo (`StaffScheduling`). Docker Desktop muss laufen.
2. `docker compose ps` – laufen `api` und `webapp` (healthy)? Wenn nicht: `docker compose up --build --wait`
   (dauert beim ersten Mal einige Minuten).
3. `python3 "Demo Pratke/demotest/demo_client.py"` – zeigt API-Status und Team. Lies den Kopf von
   `demo_client.py`: Er enthält alle Funktionen, die du brauchst.
4. Notiere die Startzeit mit `date`. **Nach 24 Minuten keine neue Berechnung mehr starten**, dann den Bericht
   schreiben.

## Spielregeln

- **Nichts am Code ändern, nichts committen, keine Pakete installieren.** Den Inhalt von `.secrets/` nie lesen
  oder ausgeben.
- Den Stack **nicht neu starten oder stoppen**, solange er läuft (alle Eingaben liegen nur im Speicher, und ein
  Neustart öffnet eine neue Gurobi-Lizenzsitzung). Am Ende laufen lassen.
- **Nur Eingaben, die die Oberfläche erlaubt**, und nur über die Funktionen in `demo_client.py`:
  - Einschränkungen: `unavailable` (heißt in der Oberfläche „Krank“, wird gutgeschrieben), `vacation`, `training`,
    `free_day` (wird nicht gutgeschrieben), `available_only` mit 1–3 erlaubten Schichten. Höchstens eine je Tag
    und Person. Zeiträume wie per ⇧-Klick mit `availability_range` (schließt Wochenenden ein).
  - Wünsche: `free_day`, `free_shift` (mit Schicht), `preferred_day`, `preferred_shift` (mit Schicht).
  - Mindestbesetzung: je Tag, Schicht und Qualifikation 0–5, nur `professional`, `assistant`, `trainee`.
  - Vormonat: nur der mit `save_plan` gespeicherte Plan genau des Vormonats (`load_history`); Laden eines Plans
    auf der Prüfseite (`load_plan`).
- Immer nur **eine Berechnung gleichzeitig** (`generate` wartet von selbst). Eine Berechnung dauert ~32 s, du
  schaffst also etwa 35 Berechnungen; plane lieber 25–30 und schau dir Ergebnisse an.
- Eingaben bleiben je Monat bestehen. Willst du einen Monat „frisch“, nimm einen anderen Monat aus deiner Liste
  oder entferne deine Einträge wieder.

## Deine Monate

| Laptop | Monate (Ketten mit Vormonat fett) |
|---|---|
| 1 | **2026-01 → 2026-02 → 2026-03**, 2027-07, 2027-08 |
| 2 | 2026-04, 2026-05, 2026-06, **2027-09 → 2027-10** |
| 3 | 2026-07, 2026-08, **2027-01 → 2027-02 → 2027-03** |
| 4 | **2026-10 → 2026-11 → 2026-12**, 2027-11 |
| 5 | 2026-09, 2027-04, 2027-05, **2027-06 → 2027-07 → 2027-08**, 2027-12 |

2026-01, 2026-02 und 2026-10 sowie 2027-07 enden an einem Samstag (Übergang ins Wochenende des Folgemonats).

## Ablauf (Vorschlag, frei abwandelbar)

1. **Einstieg (1 Lauf):** ein Monat ganz ohne Änderungen – so startet jeder Besucher.
2. **Pflegedienstleitung (~40 %):** realistische Eingaben, z. B. Urlaubswochen für 2–4 Personen, ein paar
   Krankheitstage, Fortbildungstage, Wünsche (Wochenende frei, bestimmte Schicht frei, Wunschschicht), eine
   Teilzeitkraft „nur Früh“, leicht erhöhter Wochenendbedarf oder ein Zwischendienst werktags. Schau dir danach
   mit `show_plan` einige Personen an und beurteile den Plan wie eine Leitung.
3. **Monate verketten (~25 %):** deine fett markierte Kette: Monat rechnen, wenn angenommen `save_plan`, im
   Folgemonat `load_history`, rechnen. Achte auf den Monatswechsel (gleiche Schicht am Wochenende, Nächte,
   Lücken bei Hilfskraft/Azubis).
4. **Arzt klickt herum (~25 %):** leicht zufällige Eingaben mit festem Seed (`random.Random(100*N + k)`):
   10–30 Einschränkungen, 10–30 Wünsche, 5–20 Bedarfszellen, zufällige Personen und Tage.
5. **IT-Person (~10 %, 2–3 Läufe):** Grenzfälle, z. B. Bedarf an einem Tag überall 5, eine Person den halben
   Monat krank, alle wollen denselben Samstag frei, einen falschen Vormonat laden (gleicher Monat, kaputte Datei),
   zweimal kurz nacheinander starten.

## Was du meldest

Gib während der Arbeit nach jedem Lauf die Zeile von `generate` aus. **Sofort hervorheben**, wenn:

1. **kein Plan** entsteht, der Plan leer ist oder ein HTTP-Fehler / eine unklare Meldung auftritt,
2. der Plan die **Prüfung nicht besteht** (Regel, Person, Datum notieren und die vermutete Ursache),
3. die letzte Stufe **`cons` nicht erreicht** wird (die Auswertung sagt es dir),
4. sonst etwas auffällt: viele Spät→Früh-Wechsel (> 10), Lücken trotz Standardbedarf, Laufzeit > 40 s,
   unplausible Pläne (z. B. jemand im Dienst ohne Bedarf, während Bedarf offen bleibt; deutlich ungleiche
   Wochenenden; leicht erfüllbare Wünsche nicht erfüllt).

**Bekannte Grenzen des Prototyps** – zählen, aber nicht als neu melden:
- Mit geladenem Vormonat können bei Hilfskraft und Azubis Lücken im Frühdienst entstehen, während sie Spätdienste
  ohne Bedarf haben (der Saldo ±5 h hat Vorrang).
- Eine Person nur Nachtdienst („Dauernachtwache“) oder mit sehr vielen freien Tagen erreicht ihr Soll nicht und
  der Plan wird wegen des Saldos abgelehnt.
- Fortbildung als Zeitraum über ein Wochenende (> 10 Tage am Stück) wird abgelehnt.
- Urlaub am 1. nachträglich für jemanden, der am Samstag davor im Vormonat gearbeitet hat: geteiltes Wochenende,
  Ablehnung „Gleiche Schicht am Wochenende“.
- Bei sehr vielen Wünschen oder Einschränkungen wird `cons` manchmal nicht erreicht.

## Abschlussbericht

Schreibe den Bericht auf Deutsch nach `~/Desktop/demotest-laptop-N.md` (N = deine Nummer) und gib ihn
zusätzlich vollständig im Chat aus. Die Rohdaten jeder Berechnung stehen in `~/Desktop/demotest-laeufe.jsonl`.

```
# Demo-Simulation Laptop N – <Datum, Start–Ende>
## Zusammenfassung
Anzahl Berechnungen; davon angenommen / abgelehnt / ohne Plan; cons nicht erreicht; Gesamteindruck in 2–3 Sätzen.
## Probleme (neu)
Je Problem: Monat, Eingaben (so, dass man es nachstellen kann), was passiert ist, Einschätzung (Schwere:
hoch/mittel/niedrig; Wie wahrscheinlich bei einer echten Demo?).
## Bekannte Grenzen, die aufgetreten sind
Kurz mit Anzahl.
## Eindruck als Pflegedienstleitung
Was an den Plänen überzeugt, was seltsam wirkt (konkret, mit Beispiel aus show_plan).
## Alle Läufe
Tabelle: Nr, Persona, Monat, Kurzbeschreibung der Eingaben, Prüfung, Lücken, Spät→Früh, Wünsche erfüllt/gesamt,
cons erreicht, Laufzeit.
```
