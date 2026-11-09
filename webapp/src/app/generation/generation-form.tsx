"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { generate } from "./actions";

/** The scope to generate and the start button in one row; the solver time is fixed, the job is shown by the page. */
export function GenerationForm({
  month,
  stationIds,
  running,
  scope,
}: {
  month: string;
  stationIds: number[];
  running: boolean;
  scope: React.ReactNode;
}) {
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function start() {
    setError(null);
    startTransition(async () => {
      const result = await generate(month, stationIds);
      if (!result.ok) setError(`${result.error} Es wurde kein Dienstplan gestartet.`);
    });
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end justify-between gap-4">
        {scope}
        <Button size="lg" disabled={pending || running || stationIds.length === 0} onClick={start}>
          {pending ? "Wird gestartet …" : running ? "Wird berechnet …" : "Dienstplan erstellen"}
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
