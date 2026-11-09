"use client";

import { useState, useTransition } from "react";
import { History, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { monthLabel } from "@/lib/labels";
import type { HistorySummary } from "@/lib/types";
import { loadHistory, removeHistory } from "./actions";

/**
 * The optional month before: load its saved plan file so the rules hold across the month start, or remove it again.
 * The backend checks the file; while a schedule is calculated, nothing changes here.
 */
export function HistoryPanel({
  month,
  previousName,
  history,
  running,
}: {
  month: string;
  /** The month before by name, e.g. "November 2026". */
  previousName: string;
  history: HistorySummary | null;
  running: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  // A submit handler instead of a form action: React resets a form after its action, also a failed one.
  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const files = new FormData(event.currentTarget);
    setError(null);
    startTransition(async () => {
      const result = await loadHistory(month, files);
      if (!result.ok) setError(`${result.error} Bitte den gespeicherten Dienstplan von ${previousName} wählen.`);
    });
  }

  function remove() {
    setError(null);
    startTransition(async () => {
      const result = await removeHistory(month);
      if (!result.ok) setError(result.error);
    });
  }

  return (
    <section aria-label="Vormonat" className="space-y-2 rounded-lg border bg-muted/30 p-3">
      <p className="flex items-center gap-1.5 font-medium text-foreground">
        <History className="size-4" />
        Vormonat (optional)
      </p>
      {history ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p>
            Geladen: Dienstplan {monthLabel(history.previous_month.year, history.previous_month.month).name} - Version{" "}
            {history.version} · {history.duties} Dienste. Die Regeln gelten damit auch über den Monatswechsel.
          </p>
          <Button size="sm" variant="outline" disabled={pending || running} onClick={remove}>
            <X />
            Entfernen
          </Button>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-2">
          <p>
            Den gespeicherten Dienstplan von {previousName} laden, damit Nachtdienste, Ruhezeiten, Arbeitstage am Stück
            und Wochenenden auch über den Monatswechsel stimmen. Ohne ihn gelten die Tage vor dem Monat als frei.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              name="plan"
              type="file"
              accept=".json,application/json"
              required
              aria-label={`Dienstplan von ${previousName}`}
              className="w-auto max-w-full"
            />
            <Button type="submit" size="sm" variant="outline" disabled={pending || running}>
              <Upload />
              {pending ? "Wird geprüft …" : "Vormonat laden"}
            </Button>
          </div>
        </form>
      )}
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
    </section>
  );
}
