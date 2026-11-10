import { BulletList } from "@/components/bullet-list";
import { LoadError } from "@/components/load-error";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { getHistory, getLatestGeneration } from "@/lib/api";
import { monthLabel, selectionMonthLabel } from "@/lib/labels";
import { loadPlanningScope, type ScopeSearchParams } from "@/lib/scope";
import { selectionMonth } from "@/lib/selection";
import type { GenerationJob } from "@/lib/types";
import { GenerationForm } from "./generation-form";
import { HistoryPanel } from "./history-panel";
import { JobPanel } from "./job-panel";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Dienstplan erstellen · Schichtplan Manager" };

/**
 * The job's month as `YYYY-MM`. The page shows a finished job only in its own month, so a plan of another month is
 * never taken for the selected one; a running job shows everywhere, since it blocks starting another.
 */
const jobMonth = (job: GenerationJob) =>
  selectionMonth(job.request.planning_month.year, job.request.planning_month.month);

// What the Gurobi model (api/app/solver/milp/service.py) actually reads and enforces; keep in step with it.
// The demo plans one station without a previous month, so station transfers and the days before the month are left out.
const USED = [
  "Mindestbesetzung je Schicht und Qualifikation; was fehlt, wird als Lücke ausgewiesen",
  "Urlaub, Fortbildung, freie Tage und Einschränkungen werden immer eingehalten; vor Urlaub und Fortbildung kein Spät- oder Nachtdienst",
  "Monatskonten: Sollzeit und Gutschriften, Saldo innerhalb ±5 Std.",
  "Wünsche, so weit möglich",
  "Rotation: jede Person in jedem 28-Tage-Zeitraum möglichst in allen ihren Schichtarten",
  "Nachtdienste in Blöcken von 2–3 Nächten, danach 2 Tage ganz frei",
  "Höchstens 10 Arbeitstage am Stück; Wochenende mit gleicher Schicht an beiden Tagen, nie zwei in Folge",
  "Gearbeitete Wochenenden gleichmäßig verteilt",
  "Gleichmäßige Besetzung über alle Tage und Schichten, möglichst wenige Spät-Früh-Wechsel",
  "Dienstplan des Vormonats, wenn geladen: die Regeln gelten dann auch über den Monatswechsel",
];

export default async function GenerationPage({ searchParams }: { searchParams: Promise<ScopeSearchParams> }) {
  const params = await searchParams;
  const [scope, latest] = await Promise.all([
    loadPlanningScope("/generation", params),
    getLatestGeneration().then(
      (job) => ({ job }),
      (error: Error) => ({ error: error.message }),
    ),
  ]);
  const running = "job" in latest && latest.job?.state === "running";
  const selectedIds = new Set(scope.stationIds);
  const selected = scope.stations.filter((unit) => selectedIds.has(unit.planning_unit_id));
  const period = selectionMonthLabel(scope.month);
  // The month before by name; its saved plan, if loaded, is this month's history.
  const [year, monthNumber] = scope.month.split("-").map(Number);
  const previousName = monthLabel(monthNumber === 1 ? year - 1 : year, monthNumber === 1 ? 12 : monthNumber - 1).name;
  const history = await getHistory(scope.month).catch(() => null);

  return (
    <div className="py-6">
      <PageHeader title="Dienstplan erstellen" back scope={scope} />
      {scope.error && (
        <div className="mb-6">
          <LoadError title="Stationen nicht geladen" message={scope.error} />
        </div>
      )}

      <div className="space-y-6">
        <Card aria-label="Neuer Dienstplan">
          <CardContent className="space-y-3 text-sm">
            <GenerationForm
              month={scope.month}
              stationIds={scope.stationIds}
              running={running}
              scope={
                <div className="space-y-1">
                  <h2 className="text-lg font-semibold">
                    {period.name}
                    {selected.length > 0 && <> · {selected.map((unit) => unit.display_name).join(", ")}</>}
                  </h2>
                  <p className="text-muted-foreground">
                    {selected.length ? `Ganzer Monat, ${period.range}` : "Bitte mindestens eine Station auswählen."}
                  </p>
                </div>
              }
            />
            <HistoryPanel month={scope.month} previousName={previousName} history={history} running={running} />
            <div className="space-y-1.5 border-t pt-3 text-muted-foreground">
              <p className="font-medium text-foreground">Berücksichtigt</p>
              <BulletList
                items={USED}
                label="Berücksichtigt"
                className="sm:columns-2 sm:gap-x-8 [&>li]:break-inside-avoid"
              />
            </div>
          </CardContent>
        </Card>

        {"error" in latest ? (
          <LoadError title="Berechnung nicht geladen" message={latest.error} />
        ) : latest.job && (running || jobMonth(latest.job) === scope.month) ? (
          <JobPanel job={latest.job} units={scope.stations} />
        ) : (
          <Card aria-label="Letzte Berechnung" className="border-dashed shadow-none">
            <CardContent className="text-sm">
              <h2 className="text-lg font-semibold">Letzte Berechnung</h2>
              <p className="text-muted-foreground">
                Für {period.name} noch kein Dienstplan berechnet. Mit „Dienstplan erstellen“ starten; die Berechnung
                dauert etwa eine halbe Minute.
              </p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
