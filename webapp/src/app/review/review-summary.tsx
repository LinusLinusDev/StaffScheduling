import { BulletList } from "@/components/bullet-list";
import { Facts } from "@/components/facts";
import { ProblemBox } from "@/components/problem-box";
import { StatusLine, type Tone } from "@/components/status-line";
import { Card, CardContent } from "@/components/ui/card";
import { CHECK_STATUS, RULES, missingInputs, formatDate, formatHours, monthLabel } from "@/lib/labels";
import type { CheckStatus, Rule, ScheduleReview } from "@/lib/types";

const SOURCES: Record<ScheduleReview["source"], string> = { generation: "Erstellt", import: "Geladen" };
const TIME = new Intl.DateTimeFormat("de-DE", { timeZone: "Europe/Berlin", dateStyle: "short", timeStyle: "short" });
const TONES: Record<CheckStatus, Tone> = { accepted: "success", rejected: "error", incomplete: "warning" };
// What a finding of a rule means, in German; the check's own message is English and for developers only.
const FINDING_TEXT: Partial<Record<Rule, string>> = {
  availability: "Dienst trotz Einschränkung",
  one_duty_per_day: "mehr als ein Dienst an einem Tag",
  work_and_breaks: "Schicht verletzt Höchstarbeitszeit oder Pausen",
  work_average: "im Schnitt mehr als 8 Stunden pro Werktag",
  rest: "weniger als 11 Stunden Ruhe zwischen zwei Diensten",
  consecutive_nights: "mehr als 3 Nachtdienste hintereinander",
  night_recovery: "weniger als 48 Stunden frei nach dem letzten Nachtdienst",
  replacement_rest: "kein freier Werktag als Ausgleich für einen gearbeiteten Sonn- oder Feiertag",
};

/** The schedule's counts as a ward reads them: the backend's metrics with the gaps and wishes of the check. */
function metricFacts(review: ScheduleReview, missing: number): [string, string][] {
  const { metrics } = review;
  const { wish_counts: wishes } = review.solution.check;
  const band = `±${formatHours(metrics.balance_tolerance_minutes)}`;
  const largest = `größte Abweichung ${formatHours(metrics.largest_balance_minutes, { signed: true })}`;
  const outside = metrics.balances_outside_tolerance;
  const decided = wishes.granted + wishes.denied;
  return [
    [
      "Lücken",
      missing ? `${missing} ${missing === 1 ? "unbesetzte Pflichtstelle" : "unbesetzte Pflichtstellen"}` : "keine",
    ],
    [
      "Monatssaldo",
      `${outside ? `${outside} ${outside === 1 ? "Person" : "Personen"} außerhalb` : "alle innerhalb"} ${band}, ${largest}`,
    ],
    [
      "Wünsche",
      decided + wishes.not_grantable === 0
        ? "keine eingetragen"
        : [
            decided && `${wishes.granted} von ${decided} erfüllt`,
            wishes.not_grantable && `${wishes.not_grantable} nicht erfüllbar`,
          ]
            .filter(Boolean)
            .join(", "),
    ],
    ["Wechsel Spät- auf Frühdienst", metrics.late_to_early ? String(metrics.late_to_early) : "keine"],
  ];
}

/** What a staff admin needs about the schedule under review: its scope, whether it may be used, why not, and the
 * actions to save it or load another. */
export function ReviewSummary({ review, actions }: { review: ScheduleReview; actions: React.ReactNode }) {
  const { solution, tables } = review;
  const { check } = solution;
  const period = monthLabel(review.planning_month.year, review.planning_month.month);
  const stations = review.planning_units.filter((unit) => unit.type === "station");
  const unitName = new Map(review.planning_units.map((unit) => [unit.planning_unit_id, unit.display_name]));
  const employeeName = new Map(tables.employees.map((row) => [row.employee_id, row.employee_name]));
  const [checkValue, checkDetail] = CHECK_STATUS[check.status];
  const gaps = tables.coverage.filter((row) => row.missing_count > 0);
  const missing = gaps.reduce((total, row) => total + row.missing_count, 0);
  const hint =
    check.status !== "accepted"
      ? checkDetail
      : missing > 0
        ? "Für die Lücken unten Gastpersonal anfragen"
        : "Alle Pflichtstellen sind besetzt";

  const balance = new Map(tables.employees.map((row) => [row.employee_id, row.balance_minutes]));
  const findingText = (row: (typeof check.findings)[number]) => {
    const saldo = row.employee_id === null ? undefined : balance.get(row.employee_id);
    if (row.rule === "monthly_balance" && saldo !== undefined)
      return `Saldo ${formatHours(saldo, { signed: true })}, erlaubt sind ±${formatHours(review.metrics.balance_tolerance_minutes)}`;
    return FINDING_TEXT[row.rule];
  };
  const findings = check.findings.map((row) =>
    [
      [RULES[row.rule], findingText(row)].filter(Boolean).join(": "),
      row.employee_id && employeeName.get(row.employee_id),
      row.date && formatDate(row.date),
      row.planning_unit_id && unitName.get(row.planning_unit_id),
    ]
      .filter(Boolean)
      .join(" · "),
  );
  const inputs = missingInputs(check);

  return (
    <Card aria-label="Dienstplan zur Prüfung">
      <CardContent className="space-y-5 text-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold">
              {period.name} · {stations.map((unit) => unit.display_name).join(", ")}
            </h2>
            <p className="text-muted-foreground">
              {SOURCES[review.source]} {TIME.format(new Date(review.received_at))} Uhr · {tables.duties.length} Dienste
            </p>
            <StatusLine tone={TONES[check.status]} title={checkValue} hint={hint} />
          </div>
          {actions}
        </div>

        <ProblemBox
          sections={[
            ["Verstöße", findings],
            ["Fehlende Eingaben", inputs.missing],
          ]}
        />

        {missing > 0 && (
          <section aria-label="Lücken" className="space-y-1.5 rounded-lg border border-amber-500/40 bg-amber-500/5 p-4">
            <p className="font-medium text-amber-800">
              {missing} {missing === 1 ? "unbesetzte Pflichtstelle" : "unbesetzte Pflichtstellen"} (Lücken)
            </p>
            <p className="text-muted-foreground">
              Kein einsetzbarer Mitarbeiter ist frei; für diese Schichten Gastpersonal anfragen. Im Dienstplan sind sie
              unter „Besetzung“ rot markiert.
            </p>
            <BulletList
              items={gaps.map(
                (row) =>
                  `${formatDate(row.date)} · ${row.shift_code} · ${row.qualifikation}: ${row.missing_count} ${row.missing_count === 1 ? "fehlt" : "fehlen"} (benötigt ${row.required_count})`,
              )}
            />
          </section>
        )}

        <section aria-label="Kennzahlen">
          <Facts title="Kennzahlen" facts={metricFacts(review, missing)} />
        </section>
      </CardContent>
    </Card>
  );
}
