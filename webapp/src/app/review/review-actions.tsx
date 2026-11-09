"use client";

import { useState, useTransition } from "react";
import { Download, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { loadPlan } from "./actions";

/**
 * Load a saved plan file; a rejected file leaves the shown schedule unchanged and keeps the chosen file for another
 * try. Closing the popover discards the form.
 */
function LoadMenu() {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  // A submit handler instead of a form action: React resets a form after its action, also a failed one.
  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const files = new FormData(event.currentTarget);
    setError(null);
    startTransition(async () => {
      const result = await loadPlan(files);
      if (result.ok) setOpen(false);
      else setError(`${result.error} Der bisherige Dienstplan bleibt angezeigt.`);
    });
  }

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (pending) return;
        if (next) setError(null);
        setOpen(next);
      }}
    >
      <PopoverTrigger asChild>
        <Button variant="outline">
          <Upload />
          Laden
        </Button>
      </PopoverTrigger>
      <PopoverContent role="dialog" aria-label="Laden" align="start" className="w-96 text-sm">
        <form onSubmit={submit} className="space-y-3">
          <p className="text-muted-foreground">
            Einen gespeicherten Dienstplan wieder öffnen, z. B. „Dienstplan Dezember 2026 - Version 2.json“.
          </p>
          <div className="space-y-2">
            <Label htmlFor="load-plan">Dienstplan-Datei</Label>
            <Input id="load-plan" name="plan" type="file" accept=".json,application/json" required />
          </div>
          <Button type="submit" disabled={pending}>
            {pending ? "Wird geladen …" : "Dienstplan laden"}
          </Button>
          {error && (
            <p role="alert" className="text-destructive">
              {error}
            </p>
          )}
        </form>
      </PopoverContent>
    </Popover>
  );
}

/**
 * Save the schedule under review as one file named by its month, year and version, or load a saved one; without a
 * schedule, only loading is offered.
 */
export function ReviewActions({ hasReview }: { hasReview: boolean }) {
  return (
    <div role="group" aria-label="Speichern und Laden" className="flex flex-wrap items-center gap-2">
      {hasReview && (
        <a href="/review/plan" download className={buttonVariants({ variant: "outline" })}>
          <Download />
          Speichern
        </a>
      )}
      <LoadMenu />
    </div>
  );
}
