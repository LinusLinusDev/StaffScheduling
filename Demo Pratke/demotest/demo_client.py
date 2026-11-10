"""Hilfsfunktionen für die Demo-Simulation: Eingaben wie über die Oberfläche, gegen die laufende API.

Nutzung in einem eigenen Skript (Python 3.9 reicht):

    import sys; sys.path.insert(0, "Demo Pratke/demotest")
    from demo_client import *
    availability(3, "2026-12-24", "vacation")
    wish(5, "2026-12-31", "free_day")
    job = generate("PDL Weihnachten", 2026, 12)
    show_plan(job, [3, 5, 10], "2026-12-20", "2026-12-31")

`python3 "Demo Pratke/demotest/demo_client.py"` prüft nur, ob die API erreichbar ist.
Jede Berechnung wird zusätzlich als eine Zeile JSON an ~/Desktop/demotest-laeufe.jsonl angehängt.
"""

import calendar
import datetime as dt
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter

API = "http://127.0.0.1:8000"
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PLANS = os.path.expanduser("~/Desktop/demotest-plaene")
RUNS = os.path.expanduser("~/Desktop/demotest-laeufe.jsonl")

# Schichten der Musterstation (IDs der Oberfläche)
F, Z, S, N = 1113, 1453, 1605, 1690
CODE = {F: "F", Z: "Z", S: "S", N: "N"}
# Team: 1-9 Fachkräfte (7, 8, 9 in Teilzeit 80/85/90 %), 11 und 12 Azubis; keine Hilfskraft (ID 10 frei)
FK, AZ = list(range(1, 10)), [11, 12]
ALL = FK + AZ
LEVELS = ("professional", "trainee")  # Hilfskraft und MFA sind in der Oberfläche ausgeblendet
AVAILABILITY_TYPES = ("unavailable", "vacation", "training", "free_day", "available_only")  # unavailable = "Krank"
WISH_TYPES = ("free_day", "free_shift", "preferred_day", "preferred_shift")
NAMES = {}


def call(method, path, body=None, raw=None, ctype=None):
    """Ein API-Aufruf; gibt (HTTP-Status, Antwort) zurück, auch bei Fehlern."""
    data, headers = None, {}
    if body is not None:
        data, headers = json.dumps(body).encode(), {"Content-Type": "application/json"}
    if raw is not None:
        data, headers = raw, {"Content-Type": ctype}
    request = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            text = response.read()
            kind = response.headers.get_content_type()
            return response.status, json.loads(text) if text and kind == "application/json" else text
    except urllib.error.HTTPError as error:
        text = error.read()
        try:
            return error.code, json.loads(text)
        except ValueError:
            return error.code, text


def _ok(result, what):
    status, body = result
    if status >= 300:
        print(f"   !! {what}: HTTP {status} {str(body)[:200]}", flush=True)
    return status < 300


def days(year, month):
    """Alle Tage eines Monats als date."""
    return [dt.date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]


def _day(day):
    return day.isoformat() if isinstance(day, dt.date) else day


def availability(emp, day, kind, shifts=None):
    """Einschränkung setzen; kind aus AVAILABILITY_TYPES, bei available_only die erlaubten Schichten (mind. eine)."""
    body = {"availability_type": kind}
    if shifts:
        body["shift_ids"] = list(shifts)
    return _ok(call("PUT", f"/availability/{emp}/{_day(day)}", body), f"Einschränkung {kind} {emp} {_day(day)}")


def availability_range(emp, first, last, kind, shifts=None):
    """Wie ⇧-Klick in der Oberfläche: jeder Tag von first bis last, auch Wochenenden."""
    day = dt.date.fromisoformat(_day(first))
    while day <= dt.date.fromisoformat(_day(last)):
        availability(emp, day, kind, shifts)
        day += dt.timedelta(days=1)


def remove_availability(emp, day):
    return _ok(call("DELETE", f"/availability/{emp}/{_day(day)}"), f"Einschränkung entfernen {emp} {_day(day)}")


def wish(emp, day, kind, shift=None):
    """Wunsch setzen; kind aus WISH_TYPES, bei free_shift/preferred_shift mit Schicht."""
    body = {"type": kind}
    if shift:
        body["shift_id"] = shift
    return _ok(call("PUT", f"/wishes/{emp}/{_day(day)}", body), f"Wunsch {kind} {emp} {_day(day)}")


def remove_wish(emp, day):
    return _ok(call("DELETE", f"/wishes/{emp}/{_day(day)}"), f"Wunsch entfernen {emp} {_day(day)}")


def demand(year, month, change):
    """Mindestbesetzung ändern und den ganzen Monat speichern, wie der Knopf "Speichern".

    change(day, shift, level, old) gibt den neuen Wert 0-5 zurück oder None für "unverändert".
    """
    status, config = call("GET", f"/demand?planning_unit_id=1&year={year}&month={month}")
    cells = {(c["date"], c["shift_id"], c["staff_level"]): c["required_count"] for c in config["demand"]["cells"]}
    for day in days(year, month):
        for shift in (F, Z, S, N):
            for level in LEVELS:
                key = (day.isoformat(), shift, level)
                new = change(day, shift, level, cells.get(key, 0))
                if new is not None:
                    assert 0 <= new <= 5, "die Oberfläche bietet nur 0 bis 5"
                    cells[key] = new
    body = {
        "planning_unit_id": 1,
        "planning_month": {"year": year, "month": month},
        "cells": [{"date": d, "shift_id": s, "staff_level": l, "required_count": c}
                  for (d, s, l), c in cells.items() if c > 0],
    }
    return _ok(call("PUT", "/demand", body), "Mindestbesetzung speichern")


def _multipart(content, name="plan.json"):
    boundary = uuid.uuid4().hex
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="plan"; filename="{name}"\r\n'
            "Content-Type: application/json\r\n\r\n").encode()
    return head + content + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def save_plan(name):
    """Wie "Speichern" auf der Prüfseite: der angezeigte Plan als Datei; gibt den Pfad zurück."""
    os.makedirs(PLANS, exist_ok=True)
    status, content = call("GET", "/review/plan")
    path = os.path.join(PLANS, f"{name}.json")
    with open(path, "wb") as handle:
        handle.write(content if isinstance(content, bytes) else json.dumps(content).encode())
    return path


def load_history(year, month, path):
    """Wie "Vormonat" auf der Seite Dienstplan erstellen: den gespeicherten Plan des Vormonats laden.

    Gibt (Status, Antwort) zurück; 422 mit "problem" heißt: abgelehnt (falscher Monat, nicht angenommen, ...).
    """
    with open(path, "rb") as handle:
        raw, ctype = _multipart(handle.read())
    return call("PUT", f"/history?year={year}&month={month}", raw=raw, ctype=ctype)


def remove_history(year, month):
    return call("DELETE", f"/history?year={year}&month={month}")


def load_plan(path):
    """Wie "Laden" auf der Prüfseite."""
    with open(path, "rb") as handle:
        raw, ctype = _multipart(handle.read())
    return call("POST", "/review/import-plan", raw=raw, ctype=ctype)


def generate(label, year, month):
    """Wie "Dienstplan erstellen": rechnet 30 s, wartet und gibt eine Auswertung aus; gibt den Job zurück."""
    if not NAMES:
        _load_names()
    started = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    clock = time.monotonic()
    status, job = call("POST", "/generation", {"planning_unit_ids": [1], "planning_month": {"year": year, "month": month}})
    if status >= 300:
        print(f"[{label}] !! Start abgelehnt: HTTP {status} {str(job)[:300]}", flush=True)
        return None
    while True:
        time.sleep(2)
        status, job = call("GET", "/generation")
        if job.get("state") != "running":
            break
    wall = time.monotonic() - clock
    logs = subprocess.run(["docker", "compose", "logs", "api", "--no-log-prefix", "--since", started],
                          cwd=REPO, capture_output=True, text=True).stdout.splitlines()
    passes = [line.split("(")[1].split(")")[0] for line in logs
              if "Multi-objectives: optimize objective" in line and "[gurobipy]" not in line]
    _report(label, year, month, job, wall, passes)
    return job


def _report(label, year, month, job, wall, passes):
    solution = job.get("solution")
    record = {"label": label, "month": f"{year}-{month:02d}", "wall": round(wall), "state": job.get("state")}
    if job["state"] != "completed" or not solution or not solution.get("assignments"):
        record["issues"] = [f"KEIN PLAN ODER LEER (state={job['state']}, problem={job.get('problem')}, "
                            f"error={job.get('error')}, Dienste={len((solution or {}).get('assignments') or [])})"]
        print(f"[{label}] !! {record['issues'][0]}", flush=True)
        _append(record)
        return
    check = solution["check"]
    rules = Counter(f["rule"] for f in check["findings"])
    gaps = sum(g["missing_count"] for g in solution["gaps"])
    stages = {s["name"]: s["value"] for s in solution["stages"]}
    issues = []
    if check["status"] != "accepted":
        issues.append(f"PRÜFUNG {check['status']}: {dict(rules)}")
    if "cons" not in passes:
        issues.append(f"CONS NICHT ERREICHT (letzte Stufe: {passes[-1] if passes else '-'})")
    if wall > 40:
        issues.append(f"LANGSAM {wall:.0f}s")
    if (stages.get("Min_L_to_E") or 0) > 10:
        issues.append(f"VIELE SPÄT→FRÜH: {stages.get('Min_L_to_E')}")
    record.update(check=check["status"], gaps=gaps, late_to_early=stages.get("Min_L_to_E"),
                  balance_excess=stages.get("balance_violation"), weekend_split=stages.get("weekend_start"),
                  wishes=check["wish_counts"], findings=dict(rules), issues=issues, last_stage=passes[-1] if passes else None)
    print(f"[{label}] {'!!' if issues else 'ok'} {wall:4.0f}s Prüfung={check['status']} Lücken={gaps} "
          f"Spät→Früh={stages.get('Min_L_to_E')} Wünsche={check['wish_counts']}", flush=True)
    for issue in issues:
        print(f"      -> {issue}", flush=True)
    if 0 < gaps <= 40:
        level = {"professional": "FK", "assistant": "HK", "trainee": "AZ", "mfa": "MFA"}
        print("      Lücken: " + ", ".join(f"{g['date'][5:]} {CODE[g['shift_id']]} {level[g['staff_level']]}"
                                         f"{'x' + str(g['missing_count']) if g['missing_count'] > 1 else ''}"
                                         for g in solution["gaps"]), flush=True)
    for finding in check["findings"][:8]:
        print(f"         {finding['rule']}: {NAMES.get(finding.get('employee_id'), '-')} {finding.get('date')} "
              f"{finding['message'][:100]}", flush=True)
    _append(record)


def _append(record):
    with open(RUNS, "a") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_names():
    status, body = call("GET", "/employees?planning_unit_ids=1&year=2026&month=12")
    for row in body.get("employees", []):
        NAMES[row["employee_id"]] = row["display_name"]


def plan_of(job):
    """{(Mitarbeiter-ID, 'YYYY-MM-DD'): 'F'/'Z'/'S'/'N'} des Jobs."""
    return {(a["employee_id"], a["date"]): CODE[a["shift_id"]] for a in job["solution"]["assignments"]}


def show_plan(job, employees, first, last):
    """Kompakte Ansicht wie das Raster auf der Prüfseite: je Person eine Zeile, '-' = frei."""
    if not NAMES:
        _load_names()
    plan = plan_of(job)
    day = dt.date.fromisoformat(_day(first))
    span = []
    while day <= dt.date.fromisoformat(_day(last)):
        span.append(day)
        day += dt.timedelta(days=1)
    print(" " * 18 + " ".join(d.strftime("%d") for d in span))
    print(" " * 18 + " ".join(["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][d.weekday()] for d in span))
    for emp in employees:
        print(f"{NAMES.get(emp, emp)[:17]:<18}" + " ".join(plan.get((emp, d.isoformat()), "-").rjust(2) for d in span))


if __name__ == "__main__":
    status, body = call("GET", "/status")
    print("API:", status, body)
    _load_names()
    print("Team:", NAMES)
