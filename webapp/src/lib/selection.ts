// Planning selection URL format shared by server pages and client components: `?month=YYYY-MM&stations=1,2`.

export const MONTHS = [
  "Januar",
  "Februar",
  "März",
  "April",
  "Mai",
  "Juni",
  "Juli",
  "August",
  "September",
  "Oktober",
  "November",
  "Dezember",
];

/** The years the demo offers; every month of them is tested to plan without gaps (api/tests/test_demo.py). */
export const PLANNING_YEARS = [2026, 2027] as const;

/** Whether a `YYYY-MM` month lies in the offered years. */
export function isOfferedMonth(month: string) {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(month) && PLANNING_YEARS.some((year) => month.startsWith(`${year}-`));
}

/** The selection's `YYYY-MM` month of a year and month number. */
export function selectionMonth(year: number, month: number) {
  return `${year}-${String(month).padStart(2, "0")}`;
}

/** The query string for a selection, or "" when nothing is selected. */
export function selectionSearch(month?: string | null, stations?: readonly number[] | string | null): string {
  const query = new URLSearchParams();
  if (month) query.set("month", month);
  const stationValue = typeof stations === "string" ? stations : stations?.join(",");
  if (stationValue) query.set("stations", stationValue);
  return query.size ? `?${query}` : "";
}
