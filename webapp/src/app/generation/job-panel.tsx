import Link from "next/link";
import { ProblemBox } from "@/components/problem-box";
import { StatusLine, type Tone } from "@/components/status-line";
import { buttonVariants } from "@/components/ui/button-variants";
import { Card, CardContent } from "@/components/ui/card";
import { CHECK_STATUS, RULES, SOLVER_STATUS, missingInputs, diagnosticHints, monthLabel } from "@/lib/labels";
import { selectionMonth, selectionSearch } from "@/lib/selection";
import type { GenerationJob, PlanningUnit, Rule } from "@/lib/types";
import { RefreshWhileRunning } from "./refresh-while-running";

const TIME = new Intl.DateTimeFormat("de-DE", { timeZone: "Europe/Berlin", timeStyle: "medium" });

/** Count per rule, e.g. "Ruhezeit: 2". */
function perRule(rows: { rule: Rule }[]) {
  const counts = new Map<Rule, number>();
  for (const row of rows) counts.set(row.rule, (counts.get(row.rule) ?? 0) + 1);
  return [...counts].map(([rule, count]) => `${RULES[rule]}: ${count}`);
}

/** The outcome in one sentence a staff admin can act on, and what to do next. */
function headline(job: GenerationJob): { tone: Tone; title: string; hint: string } {
  const { solution } = job;
  if (job.state === "running")
    return { tone: "busy", title: "Dienstplan wird berechnet …", hint: "Die Seite aktualisiert sich selbst." };
  if (job.problem === "solver_unavailable")
    return {
      tone: "error",
      title: "Berechnung nicht möglich",
      hint: "Der Solver kann seine Lizenz nicht prüfen, meist fehlt die Internetverbindung. WLAN prüfen und erneut starten.",
    };
  if (job.state === "failed" || !solution)
    return { tone: "error", title: "Berechnung fehlgeschlagen", hint: "Bitte erneut starten." };
  if (solution.status === "infeasible")
    return {
      tone: "error",
      title: "Kein Dienstplan möglich",
      hint: "Die Eingaben widersprechen sich; die Hinweise nennen, was nicht erreichbar ist.",
    };
  if (solution.status === "unknown" || solution.status === "model_invalid")
    return { tone: "error", title: SOLVER_STATUS[solution.status][0], hint: "Bitte erneut starten." };
  const status = solution.check?.status;
  if (status === "accepted")
    return {
      tone: "success",
      title: "Dienstplan erstellt, Regeln eingehalten",
      hint: "Unter „Dienstplan prüfen“ ansehen.",
    };
  if (status === "incomplete")
    return {
      tone: "warning",
      title: "Dienstplan erstellt, aber unvollständig geprüft",
      hint: "Für eine Regel fehlen Eingaben, siehe Hinweise.",
    };
  return {
    tone: "error",
    title: "Dienstplan erstellt, aber mit Regelverstößen",
    hint: "Die Hinweise nennen die verletzten Regeln.",
  };
}

/** Time, check, duty and gap count of the run. */
function jobFacts(job: GenerationJob): [string, string][] {
  const { solution } = job;
  const running = job.state === "running";
  const check = solution?.check;
  const end = job.finished_at ? TIME.format(new Date(job.finished_at)) : "…";
  return [
    ["Zeit", `${TIME.format(new Date(job.started_at))} – ${end} Uhr`],
    ["Prüfung", check ? CHECK_STATUS[check.status][0] : running ? "Wartet auf Plan" : "Kein Plan zu prüfen"],
    ["Dienste", solution ? String(solution.assignments.length) : "–"],
    ["Lücken", check ? String(check.scores.gaps) : "–"],
  ];
}

/** The latest run: one sentence on the outcome, a compact fact row and the hints that explain an unusable run. */
export function JobPanel({ job, units }: { job: GenerationJob; units: PlanningUnit[] }) {
  const { planning_month: month, planning_unit_ids: stationIds, timeout_seconds } = job.request;
  const name = (id: number) => units.find((unit) => unit.planning_unit_id === id)?.display_name ?? `Station ${id}`;
  const { solution } = job;
  const check = solution?.check;
  const period = monthLabel(month.year, month.month);

  return (
    <Card aria-label="Letzte Berechnung">
      <CardContent className="space-y-4 text-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold">Letzte Berechnung</h2>
            <p className="text-muted-foreground">
              {period.name} ({period.range}) · {stationIds.map(name).join(", ")}
            </p>
            <StatusLine {...headline(job)} />
          </div>
          {check && (
            <Link
              className={buttonVariants({ variant: check.status === "accepted" ? "default" : "outline" })}
              href={`/review${selectionSearch(selectionMonth(month.year, month.month), stationIds)}`}
            >
              Dienstplan prüfen
            </Link>
          )}
        </div>

        {job.state === "running" && <RefreshWhileRunning startedAt={job.started_at} timeoutSeconds={timeout_seconds} />}

        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-lg border bg-muted/30 px-4 py-3 sm:grid-cols-4">
          {jobFacts(job).map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="font-medium">{value}</dd>
            </div>
          ))}
        </dl>

        <ProblemBox
          sections={[
            ["Hinweise", diagnosticHints(solution?.diagnostics ?? [])],
            ["Verstöße", perRule(check?.findings ?? [])],
            ["Fehlende Eingaben", missingInputs(check).missing],
          ]}
        />
      </CardContent>
    </Card>
  );
}
