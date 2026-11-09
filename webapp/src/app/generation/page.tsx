import { BulletList } from "@/components/bullet-list";
import { LoadError } from "@/components/load-error";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { getLatestGeneration } from "@/lib/api";
import { selectionMonthLabel } from "@/lib/labels";
import { loadPlanningScope, type ScopeSearchParams } from "@/lib/scope";
import { GenerationForm } from "./generation-form";
import { JobPanel } from "./job-panel";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Dienstplan erstellen · Schichtplan Manager" };

// What the Gurobi model (api/app/solver/milp/service.py) actually reads and enforces; keep in step with it.
const USED = [
  "Mindestbesetzung je Station, Schicht und Qualifikation; was fehlt, wird als Lücke ausgewiesen",
  "Urlaub, Fortbildung, freie Tage und Einschränkungen werden immer eingehalten",
  "Monatskonten: Sollzeit und Gutschriften, Saldo möglichst innerhalb ±7:40 Std.",
  "Wünsche und Einsatz auf der Stammstation, so weit möglich",
  "Nachtdienste in Blöcken von 2–3 Nächten, danach 2 freie Tage",
  "Höchstens 10 Arbeitstage am Stück und nie zwei Wochenenden in Folge",
  "Gleichmäßige Besetzung über alle Tage und Schichten, möglichst wenige Spät-Früh-Wechsel",
  "Dienste der Tage vor dem Monat, damit die Regeln auch am Monatswechsel gelten",
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
        ) : latest.job ? (
          <JobPanel job={latest.job} units={scope.stations} />
        ) : (
          <Card aria-label="Letzte Berechnung" className="border-dashed shadow-none">
            <CardContent className="text-sm">
              <h2 className="text-lg font-semibold">Letzte Berechnung</h2>
              <p className="text-muted-foreground">
                Noch kein Dienstplan berechnet. Mit „Dienstplan erstellen“ starten; die Berechnung dauert etwa eine
                halbe Minute.
              </p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
