import Link from "next/link";
import { LoadError } from "@/components/load-error";
import { PageHeader } from "@/components/page-header";
import { buttonVariants } from "@/components/ui/button-variants";
import { Card, CardContent } from "@/components/ui/card";
import { getReview } from "@/lib/api";
import { monthLabel } from "@/lib/labels";
import { loadPlanningScope, type PlanningScope, type ScopeSearchParams } from "@/lib/scope";
import { selectionMonth, selectionSearch } from "@/lib/selection";
import type { ScheduleReview } from "@/lib/types";
import { AccountTable } from "./account-table";
import { ReviewActions } from "./review-actions";
import { ReviewSummary } from "./review-summary";
import { ScheduleGrid } from "./schedule-grid";
import { WishTable } from "./wish-table";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Dienstplan prüfen · Schichtplan Manager" };

/** The review's month as `YYYY-MM` with its name, and its stations, for comparing with and linking to a selection. */
function reviewScope(review: ScheduleReview) {
  const { year, month } = review.planning_month;
  const stations = review.planning_units.filter((unit) => unit.type === "station");
  return { month: selectionMonth(year, month), monthName: monthLabel(year, month).name, stations };
}

/**
 * Whether the review belongs to the selected month. The demo offers one station, so only the month is compared: a
 * loaded plan of another station (such as one saved by the full version) is still shown in its month.
 */
function isSelected(own: ReturnType<typeof reviewScope>, scope: PlanningScope) {
  return own.month === scope.month;
}

export default async function ReviewPage({ searchParams }: { searchParams: Promise<ScopeSearchParams> }) {
  const params = await searchParams;
  const [scope, current] = await Promise.all([
    loadPlanningScope("/review", params),
    getReview().then(
      (review) => ({ review }),
      (error: Error) => ({ error: error.message }),
    ),
  ]);
  const review = "review" in current ? current.review : null;
  const own = review && reviewScope(review);
  const matches = own !== null && isSelected(own, scope);
  const actions = <ReviewActions hasReview={matches} />;

  return (
    <div className="py-6">
      <PageHeader title="Dienstplan prüfen" back scope={scope} />
      <div className="space-y-6">
        {"error" in current && <LoadError title="Dienstplan nicht geladen" message={current.error} />}
        {review && matches ? (
          <>
            <ReviewSummary review={review} actions={actions} />
            <WishTable review={review} />
            <ScheduleGrid review={review} />
            <AccountTable review={review} />
          </>
        ) : (
          <Card className={review ? undefined : "border-dashed shadow-none"}>
            <CardContent className="flex flex-wrap items-start justify-between gap-4 text-sm">
              {own ? (
                <div className="space-y-2">
                  <h2 className="text-lg font-semibold">Dienstplan für einen anderen Monat</h2>
                  <p className="text-muted-foreground">
                    Der zuletzt erstellte oder geladene Dienstplan gehört zu {own.monthName}.
                  </p>
                  <Link
                    className={buttonVariants({ variant: "outline" })}
                    href={`/review${selectionSearch(
                      own.month,
                      own.stations.map((unit) => unit.planning_unit_id),
                    )}`}
                  >
                    Zu {own.monthName} wechseln
                  </Link>
                </div>
              ) : (
                <div className="space-y-1">
                  <h2 className="text-lg font-semibold">Noch kein Dienstplan</h2>
                  <p className="text-muted-foreground">
                    Unter „Dienstplan erstellen“ einen Plan berechnen lassen oder einen gespeicherten Plan laden.
                  </p>
                </div>
              )}
              {actions}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
