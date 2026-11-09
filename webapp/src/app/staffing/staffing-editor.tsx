"use client";

import { useId, useState, useTransition } from "react";
import { Disclosure } from "@/components/disclosure";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { STAFF_LEVEL_LABELS, WEEKDAYS, formatDate } from "@/lib/labels";
import type { DayType, DemandConfiguration, StaffLevel } from "@/lib/types";
import { cn } from "@/lib/utils";
import { expandPattern, saveDemand } from "./actions";
import {
  MAX_REQUIRED_COUNT,
  cellsOf,
  changesFrom,
  countAt,
  gridOf,
  withCount,
  withLevelFrom,
  type DemandGrid,
} from "./demand-grid";

// The demo station's staff levels; MFA has no staff there, so it is not offered.
const LEVELS = (Object.keys(STAFF_LEVEL_LABELS) as StaffLevel[]).filter((level) => level !== "mfa");
const COUNTS = Array.from({ length: MAX_REQUIRED_COUNT + 1 }, (_, count) => count);
// Counts are chosen from a list, so nothing invalid can be typed; centered under their shift heading.
const COUNT_SELECT =
  "mx-auto block h-9 w-16 rounded-md border border-input bg-background px-2 text-sm shadow-xs [text-align-last:center] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
// An unsaved cell: a thicker amber border and bold digits, so the mark does not rely on color alone.
const CHANGED_INPUT = "border-2 border-amber-500 bg-amber-50 font-semibold dark:bg-amber-950";

/** A count from 0 to the maximum; the only way to enter staffing, so it is always valid. */
function CountSelect({
  value,
  onChange,
  className,
  ...aria
}: {
  value: number;
  onChange: (count: number) => void;
  className?: string;
  "aria-label": string;
  "aria-describedby"?: string;
  title?: string;
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(Number(event.target.value))}
      className={cn(COUNT_SELECT, className)}
      {...aria}
    >
      {COUNTS.map((count) => (
        <option key={count} value={count}>
          {count}
        </option>
      ))}
    </select>
  );
}
const DAY_TYPES: Array<{ type: DayType; label: string }> = [
  ...(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"] as const).map((type, index) => ({
    type,
    label: WEEKDAYS[index],
  })),
  { type: "holiday", label: "Feiertag" },
];

export function StaffingEditor({ month, configuration }: { month: string; configuration: DemandConfiguration }) {
  const { calendar, shifts, planning_unit_id: stationId } = configuration;
  const [saved, setSaved] = useState<DemandGrid>(() => gridOf(configuration.demand?.cells ?? []));
  const [grid, setGrid] = useState<DemandGrid>(saved);
  const [level, setLevel] = useState<StaffLevel>("professional");
  const [isSaved, setIsSaved] = useState(configuration.demand !== null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, startTransition] = useTransition();
  const changes = changesFrom(grid, saved);
  const markId = useId();
  const dirty = changes.size > 0;

  function setCount(date: string, shiftId: number, count: number) {
    setGrid((current) => withCount(current, date, shiftId, level, count));
    setMessage(null);
  }

  function save() {
    startTransition(async () => {
      const result = await saveDemand(month, stationId, cellsOf(grid));
      if (result.ok) {
        setSaved(grid);
        setIsSaved(true);
        setMessage({ ok: true, text: "Mindestbesetzung gespeichert." });
      } else {
        setMessage({ ok: false, text: `${result.error} Änderungen wurden nicht gespeichert.` });
      }
    });
  }

  return (
    <Card aria-labelledby={`${markId}-title`}>
      <CardHeader>
        <CardTitle id={`${markId}-title`}>Tägliche Mindestbesetzung</CardTitle>
        <CardDescription>
          Benötigte Personen je Schicht, 0 bis {MAX_REQUIRED_COUNT}. Geänderte Felder bleiben markiert, bis sie
          gespeichert oder zurückgesetzt sind.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!isSaved && (
          <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
            Für diesen Monat ist noch keine Mindestbesetzung gespeichert.
          </p>
        )}
        <div className="z-10 -mx-2 flex flex-wrap items-center justify-between gap-3 bg-card px-2 py-2 md:sticky md:top-0">
          <div role="tablist" aria-label="Qualifikation" className="flex flex-wrap gap-1 rounded-lg bg-muted p-1">
            {LEVELS.map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={level === value}
                onClick={() => setLevel(value)}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-3 py-1 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  level === value ? "bg-background font-medium shadow-sm" : "text-muted-foreground",
                )}
              >
                {STAFF_LEVEL_LABELS[value]}
                {changes.hasLevel(value) && (
                  <>
                    <span aria-hidden className="size-1.5 rounded-full bg-amber-500" />
                    <span className="sr-only">(geändert)</span>
                  </>
                )}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {dirty && (
              <span className="text-sm text-muted-foreground">
                {changes.size === 1 ? "1 ungespeicherte Änderung" : `${changes.size} ungespeicherte Änderungen`}
              </span>
            )}
            <Button variant="outline" disabled={!dirty || pending} onClick={() => setGrid(saved)}>
              Zurücksetzen
            </Button>
            <Button disabled={pending || (!dirty && isSaved)} onClick={save}>
              Speichern
            </Button>
          </div>
        </div>
        {message && (
          <p
            role={message.ok ? "status" : "alert"}
            className={cn("text-sm", message.ok ? "text-green-700" : "text-destructive")}
          >
            {message.text}
          </p>
        )}

        <PatternPanel
          month={month}
          stationId={stationId}
          shifts={shifts}
          level={level}
          grid={grid}
          onApply={(next) => {
            setGrid(next);
            setMessage(null);
          }}
        />

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Datum</TableHead>
              {shifts.map((shift) => (
                <TableHead key={shift.shift_id} className="text-center">
                  {shift.code}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {calendar.map((day) => (
              <TableRow key={day.date} className={cn((day.weekday > 5 || day.public_holiday) && "bg-muted/40")}>
                <TableCell className="whitespace-nowrap">
                  {WEEKDAYS[day.weekday - 1]} {formatDate(day.date)}
                  {day.public_holiday && (
                    <span className="block text-xs text-muted-foreground">{day.public_holiday}</span>
                  )}
                </TableCell>
                {shifts.map((shift) => {
                  const count = countAt(grid, day.date, shift.shift_id, level);
                  const before = changes.savedCount(day.date, shift.shift_id, level);
                  const mark = `${markId}-${day.date}-${shift.shift_id}`;
                  return (
                    <TableCell key={shift.shift_id} className="text-center">
                      {before !== undefined && (
                        <span id={mark} className="sr-only">
                          Geändert, gespeichert: {before}
                        </span>
                      )}
                      <CountSelect
                        aria-label={`${shift.code} am ${formatDate(day.date)}`}
                        aria-describedby={before === undefined ? undefined : mark}
                        title={before === undefined ? undefined : `Gespeichert: ${before}`}
                        value={count}
                        onChange={(next) => setCount(day.date, shift.shift_id, next)}
                        className={cn(before !== undefined && CHANGED_INPUT)}
                      />
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

/** Previews a weekly pattern via the backend calendar and applies it to the unsaved grid only after confirmation. */
function PatternPanel({
  month,
  stationId,
  shifts,
  level,
  grid,
  onApply,
}: {
  month: string;
  stationId: number;
  shifts: DemandConfiguration["shifts"];
  level: StaffLevel;
  grid: DemandGrid;
  onApply: (grid: DemandGrid) => void;
}) {
  const [pattern, setPattern] = useState<Record<string, number>>({});
  const patternKey = (type: DayType, shiftId: number) => `${level}|${type}|${shiftId}`;
  // A preview belongs to the grid and qualification it was computed from; after any later edit or tab change
  // it is no longer shown, so applying it can never undo newer edits.
  const [computed, setPreview] = useState<{
    base: DemandGrid;
    level: StaffLevel;
    grid: DemandGrid;
    changedDates: string[];
  } | null>(null);
  const preview = computed?.base === grid && computed.level === level ? computed : null;
  const [error, setError] = useState<string | null>(null);
  const [previewing, startPreview] = useTransition();

  function showPreview() {
    const cells = DAY_TYPES.flatMap(({ type }) =>
      shifts.map((shift) => ({
        day_type: type,
        shift_id: shift.shift_id,
        staff_level: level,
        required_count: pattern[patternKey(type, shift.shift_id)] ?? 0,
      })),
    );
    startPreview(async () => {
      setError(null);
      const result = await expandPattern(month, stationId, cells);
      if (!result.ok) {
        setError(result.error);
        return;
      }
      setPreview({ base: grid, level, ...withLevelFrom(grid, gridOf(result.cells), level) });
    });
  }

  return (
    <Disclosure title="Wochenmuster anwenden">
      <p className="text-sm text-muted-foreground">
        Muster für {STAFF_LEVEL_LABELS[level]} auf alle Tage dieses Monats übertragen. Feiertage (NRW) nutzen die Zeile
        Feiertag. Das Muster wird nicht gespeichert und gilt nicht für andere Monate.
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Tag</TableHead>
            {shifts.map((shift) => (
              <TableHead key={shift.shift_id} className="text-center">
                {shift.code}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {DAY_TYPES.map(({ type, label }) => (
            <TableRow key={type}>
              <TableCell>{label}</TableCell>
              {shifts.map((shift) => {
                const at = patternKey(type, shift.shift_id);
                const count = pattern[at] ?? 0;
                return (
                  <TableCell key={shift.shift_id} className="text-center">
                    <CountSelect
                      aria-label={`Muster ${shift.code} ${label}`}
                      value={count}
                      onChange={(next) => {
                        setPattern((current) => ({ ...current, [at]: next }));
                        setPreview(null);
                      }}
                    />
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Button variant="outline" disabled={previewing} onClick={showPreview}>
        Vorschau
      </Button>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {preview &&
        (preview.changedDates.length ? (
          <div role="region" aria-label="Vorschau" className="space-y-2 rounded-md border p-3 text-sm">
            <p>
              {preview.changedDates.length} Tage werden ersetzt:{" "}
              {preview.changedDates.map((date) => formatDate(date).slice(0, 6)).join(", ")}
            </p>
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={() => {
                  onApply(preview.grid);
                  setPreview(null);
                }}
              >
                Übernehmen
              </Button>
              <Button size="sm" variant="outline" onClick={() => setPreview(null)}>
                Verwerfen
              </Button>
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Das Muster ändert keinen Tag.</p>
        ))}
    </Disclosure>
  );
}
