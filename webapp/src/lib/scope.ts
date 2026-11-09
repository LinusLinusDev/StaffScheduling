import "server-only";
import { redirect } from "next/navigation";
import { getPlanningOptions } from "@/lib/api";
import { PLANNING_YEARS, isOfferedMonth, selectionMonth, selectionSearch } from "@/lib/selection";
import type { PlanningUnit } from "@/lib/types";

export interface ScopeSearchParams {
  month?: string;
  stations?: string;
}

export interface PlanningScope {
  month: string;
  stationIds: number[];
  stations: PlanningUnit[];
  error?: string;
}

/**
 * The month after the current one as `YYYY-MM`, the month a ward usually plans next; outside the offered years the
 * nearest offered month.
 */
function defaultMonth() {
  const today = new Date();
  const next = selectionMonth(
    today.getMonth() === 11 ? today.getFullYear() + 1 : today.getFullYear(),
    ((today.getMonth() + 1) % 12) + 1,
  );
  if (isOfferedMonth(next)) return next;
  const first = selectionMonth(PLANNING_YEARS[0], 1);
  return next < first ? first : selectionMonth(PLANNING_YEARS[PLANNING_YEARS.length - 1], 12);
}

/**
 * Read the planning month from the URL and load the month's stations, which are always all selected: the demo
 * plans one station, so there is nothing to choose. A missing month, or one outside the offered years, redirects
 * to the default month.
 */
export async function loadPlanningScope(pathname: string, params: ScopeSearchParams): Promise<PlanningScope> {
  const month = params.month ?? "";
  if (!isOfferedMonth(month)) {
    redirect(`${pathname}${selectionSearch(defaultMonth())}`);
  }

  let stations: PlanningUnit[];
  try {
    stations = (await getPlanningOptions(month)).planning_units;
  } catch (error) {
    return { month, stationIds: [], stations: [], error: (error as Error).message };
  }
  return { month, stationIds: stations.map((unit) => unit.planning_unit_id), stations };
}
