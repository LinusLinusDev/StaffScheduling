"use client";

import { useState, useTransition } from "react";
import { ChevronDown, Download, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { importFiles } from "./actions";

const FILE_LABELS: Record<string, string> = { "input.json": "Eingaben", "result.json": "Ergebnis" };

/** Save the schedule under review as its two files, to load it again later and compare it with others. */
function SaveMenu({ files }: { files: readonly string[] }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline">
          <Download />
          Speichern
          <ChevronDown />
        </Button>
      </PopoverTrigger>
      <PopoverContent role="dialog" aria-label="Speichern" align="start" className="w-72 p-1">
        {files.map((name) => (
          <a
            key={name}
            href={`/review/files/${name}`}
            download
            className={cn(buttonVariants({ variant: "ghost" }), "w-full justify-start")}
          >
            {name} ({FILE_LABELS[name] ?? name})
          </a>
        ))}
        <p className="px-3 py-2 text-xs text-muted-foreground">
          Beide Dateien speichern. Mit „Laden“ lässt sich der Dienstplan später wieder öffnen.
        </p>
      </PopoverContent>
    </Popover>
  );
}

/**
 * Load a saved input.json/result.json pair; a rejected pair leaves the shown schedule unchanged and keeps the
 * chosen files for another try. Closing the popover discards the form.
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
      const result = await importFiles(files);
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
            Einen gespeicherten Dienstplan wieder öffnen: input.json und result.json desselben Plans wählen.
          </p>
          <div className="space-y-2">
            <Label htmlFor="import-input">input.json</Label>
            <Input id="import-input" name="input" type="file" accept=".json,application/json" required />
          </div>
          <div className="space-y-2">
            <Label htmlFor="import-result">result.json</Label>
            <Input id="import-result" name="result" type="file" accept=".json,application/json" required />
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

/** Save the schedule under review, or load a saved one; without a schedule, only loading is offered. */
export function ReviewActions({ hasReview, files }: { hasReview: boolean; files: readonly string[] }) {
  return (
    <div role="group" aria-label="Speichern und Laden" className="flex flex-wrap items-center gap-2">
      {hasReview && <SaveMenu files={files} />}
      <LoadMenu />
    </div>
  );
}
