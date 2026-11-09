"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const REFRESH_MS = 2_000;
// Allowance beyond the solver time for reading the input and checking the result.
const MARGIN_MS = 60_000;

/**
 * While the job runs: a countdown with a progress bar to the end of its solver time, and a page refresh every two
 * seconds that shows the result once it is there; after the solver time plus a margin it stops refreshing.
 */
export function RefreshWhileRunning({ startedAt, timeoutSeconds }: { startedAt: string; timeoutSeconds: number }) {
  const router = useRouter();
  const start = Date.parse(startedAt);
  const end = start + timeoutSeconds * 1000;
  const [now, setNow] = useState(() => Date.now());
  const overdue = now > end + MARGIN_MS;

  useEffect(() => {
    if (overdue) return;
    const tick = setInterval(() => setNow(Date.now()), 250);
    const refresh = setInterval(() => router.refresh(), REFRESH_MS);
    return () => {
      clearInterval(tick);
      clearInterval(refresh);
    };
  }, [overdue, router]);

  if (overdue)
    return (
      <p role="alert" className="text-sm text-destructive">
        Die Berechnung dauert länger als erwartet. Bitte die Seite neu laden.
      </p>
    );
  const left = Math.max(0, Math.ceil((end - now) / 1000));
  const share = Math.min(1, Math.max(0, (now - start) / (end - start)));
  return (
    <div className="space-y-1.5" role="status" aria-live="off">
      <div
        className="h-2 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-label="Fortschritt der Berechnung"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(share * 100)}
      >
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-300"
          style={{ width: `${share * 100}%` }}
        />
      </div>
      <p className="text-muted-foreground">{left > 0 ? `Noch etwa ${left} s` : "Gleich fertig …"}</p>
    </div>
  );
}
