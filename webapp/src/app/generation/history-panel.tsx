"use client";

import { useState, useTransition } from "react";
import { History, X } from "lucide-react";
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

  // Choosing the file loads it at once: a chosen file that was never sent must not look like a loaded month before.
  function choose(event: React.ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    if (!file) return;
    const files = new FormData();
    files.append("plan", file);
    setError(null);
    startTransition(async () => {
      const result = await loadHistory(month, files);
      if (!result.ok) {
        setError(`${result.error} Bitte den gespeicherten Dienstplan von ${previousName} wählen.`);
        // empty again, so that choosing the same file once more loads it again
        input.value = "";
      }
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
        <div className="space-y-2">
          <p>
            Den gespeicherten Dienstplan von {previousName} auswählen, damit Nachtdienste, Ruhezeiten, Arbeitstage am
            Stück und Wochenenden auch über den Monatswechsel stimmen. Er wird sofort geprüft und geladen. Ohne ihn
            gelten die Tage vor dem Monat als frei.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              name="plan"
              type="file"
              accept=".json,application/json"
              disabled={pending || running}
              onChange={choose}
              aria-label={`Dienstplan von ${previousName}`}
              className="w-auto max-w-full"
            />
            {pending && <span className="text-muted-foreground">Wird geprüft …</span>}
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
    </section>
  );
}
