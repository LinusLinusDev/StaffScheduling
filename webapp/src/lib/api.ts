import "server-only";
import type {
  AvailabilityEntry,
  DemandCell,
  DemandConfiguration,
  EmployeeCalendar,
  EmployeeSummary,
  GenerationJob,
  MonthlyDemand,
  PatternRequirement,
  PlanningInspection,
  PlanningOptions,
  BundleProblem,
  HistoryProblem,
  HistorySummary,
  ScheduleReview,
  WishEntry,
  WriteProblem,
} from "@/lib/types";

const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

const INVALID_SELECTION = "Ungültige Auswahl. Bitte die Seite neu laden.";
const INCOMPLETE = "Daten unvollständig. Bitte die Seite neu laden.";
/** Any write the backend rolled back because another writer changed the same TimeOffice rows. */
const CONCURRENT_PROBLEM: WriteProblem = "concurrent";
const CONCURRENT = "TimeOffice wurde gleichzeitig geändert. Nichts wurde gespeichert; bitte erneut versuchen.";

/** A failed API call: a German message for the user, the HTTP status and a failed TimeOffice stage, if any. */
class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly stage?: string,
  ) {
    super(message);
  }
}

/**
 * One API call's response; failures become `ApiError`s, `invalid` and `incomplete` describing a 422 and 409 for
 * this call. A `FormData` body is sent as multipart; `problems` names a 422 or 409 by the `problem` code in its
 * body; a rolled-back write that collided with other TimeOffice changes (`concurrent`) is named for every call.
 */
async function send(
  method: "GET" | "PUT" | "POST" | "DELETE",
  path: string,
  {
    params,
    body,
    invalid = INVALID_SELECTION,
    incomplete = INCOMPLETE,
    problems,
    timeoutSeconds = 10,
  }: {
    params?: URLSearchParams;
    body?: unknown;
    invalid?: string;
    incomplete?: string;
    problems?: Record<string, string>;
    timeoutSeconds?: number;
  } = {},
): Promise<Response> {
  const json = body !== undefined && !(body instanceof FormData);
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}${params ? `?${params}` : ""}`, {
      method,
      headers: json ? { "Content-Type": "application/json" } : undefined,
      body: json ? JSON.stringify(body) : (body as FormData | undefined),
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutSeconds * 1000),
    });
  } catch {
    throw new ApiError("Die Anwendung antwortet nicht. Bitte kurz warten und die Seite neu laden.");
  }
  if (response.status === 422 || response.status === 409) {
    const problem = (await response.json().catch(() => null))?.problem;
    const message = problem === CONCURRENT_PROBLEM ? CONCURRENT : problems?.[problem];
    throw new ApiError(message ?? (response.status === 422 ? invalid : incomplete), response.status);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(unavailableMessage(body), response.status, body?.stage);
  }
  return response;
}

/** One API call's JSON body, or nothing for `204`. */
async function request<T>(
  method: "GET" | "PUT" | "POST" | "DELETE",
  path: string,
  options?: Parameters<typeof send>[2],
): Promise<T> {
  const response = await send(method, path, options);
  return response.status === 204 ? (undefined as T) : response.json();
}

/** A failed TimeOffice query (schema, permissions) is told apart from an unreachable backend or database. */
function unavailableMessage(body: { integration?: string; stage?: string } | null) {
  if (body?.integration === "timeoffice" && body.stage === "query") {
    return "TimeOffice-Abfrage fehlgeschlagen. Datenbankschema und Berechtigungen prüfen.";
  }
  return "Die Anwendung antwortet nicht. Bitte kurz warten und die Seite neu laden.";
}

/** The `YYYY-MM` selection month as the API's year and month numbers. */
function planningMonth(month: string) {
  const [year, monthNumber] = month.split("-").map(Number);
  return { year, month: monthNumber };
}

function monthQuery(month: string) {
  const { year, month: monthNumber } = planningMonth(month);
  return new URLSearchParams({ year: String(year), month: String(monthNumber) });
}

function selectionQuery(month: string, stationIds: number[]) {
  const params = monthQuery(month);
  for (const id of stationIds) params.append("planning_unit_ids", String(id));
  return params;
}

/** PUT an entry at `path`, or DELETE it when `entry` is `null`. */
function putOrDelete(path: string, entry: object | null, invalid: string) {
  return entry ? request<void>("PUT", path, { body: entry, invalid }) : request<void>("DELETE", path, { invalid });
}

export function getPlanningOptions(month: string) {
  return request<PlanningOptions>("GET", "/planning/options", { params: monthQuery(month) });
}

export function getEmployees(month: string, stationIds: number[]) {
  return request<PlanningInspection>("GET", "/employees", { params: selectionQuery(month, stationIds) });
}

/** The selection's employees by name; unlike `getEmployees` it needs no complete monthly accounts. */
export function getPlanningEmployees(month: string, stationIds: number[]) {
  return request<EmployeeSummary[]>("GET", "/planning/employees", { params: selectionQuery(month, stationIds) });
}

const INVALID_ENTRY = "Eintrag ungültig. Mitarbeiter, Datum, Art und Schichten prüfen.";

export function getEmployeeCalendar(month: string, employeeId: number) {
  const params = monthQuery(month);
  params.set("employee_id", String(employeeId));
  return request<EmployeeCalendar>("GET", "/availability", { params, invalid: INVALID_ENTRY });
}

/** Replace the employee's availability on that date; `null` removes it. */
export function setAvailability(employeeId: number, date: string, entry: AvailabilityEntry | null) {
  return putOrDelete(`/availability/${employeeId}/${date}`, entry, INVALID_ENTRY);
}

/** Replace the employee's wish on that date; `null` removes it. */
export function setWish(employeeId: number, date: string, entry: WishEntry | null) {
  return putOrDelete(`/wishes/${employeeId}/${date}`, entry, INVALID_ENTRY);
}

const INVALID_DEMAND = "Mindestbesetzung ungültig. Anzahlen von 0 bis 5 wählen.";

export function getDemand(month: string, stationId: number) {
  const params = monthQuery(month);
  params.set("planning_unit_id", String(stationId));
  return request<DemandConfiguration>("GET", "/demand", { params, invalid: INVALID_DEMAND });
}

export function putDemand(month: string, stationId: number, cells: DemandCell[]) {
  const body = { planning_unit_id: stationId, planning_month: planningMonth(month), cells };
  return request<MonthlyDemand>("PUT", "/demand", { body, invalid: INVALID_DEMAND });
}

export function previewPattern(month: string, stationId: number, cells: PatternRequirement[]) {
  const body = { planning_unit_id: stationId, planning_month: planningMonth(month), cells };
  return request<MonthlyDemand>("POST", "/demand/pattern", { body, invalid: INVALID_DEMAND });
}

const INVALID_GENERATION = "Dienstplan konnte nicht gestartet werden. Bitte die Seite neu laden.";
const INCOMPLETE_GENERATION = "Eingaben unvollständig. Bitte die Mindestbesetzung prüfen und speichern.";

/** Validate the full month's input and start solving it with the backend's fixed time; the job runs on there. */
export async function startGeneration(month: string, stationIds: number[]) {
  const body = { planning_unit_ids: stationIds, planning_month: planningMonth(month) };
  try {
    return await request<GenerationJob>("POST", "/generation", {
      body,
      invalid: INVALID_GENERATION,
      incomplete: INCOMPLETE_GENERATION,
    });
  } catch (error) {
    // 423: the backend solves one generation at a time.
    if (error instanceof ApiError && error.status === 423) {
      throw new ApiError("Es wird bereits ein Dienstplan berechnet. Nach dessen Ende erneut starten.", 423);
    }
    throw error;
  }
}

/** The latest generation since the API started, or `null` if there is none (also after a restart). */
export async function getLatestGeneration(): Promise<GenerationJob | null> {
  try {
    return await request<GenerationJob>("GET", "/generation");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** The schedule under review, or `null` without one (also after a restart). */
export async function getReview(): Promise<ScheduleReview | null> {
  try {
    return await request<ScheduleReview>("GET", "/review");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

const IMPORT_PROBLEMS: Record<BundleProblem, string> = {
  malformed: "Das ist keine gespeicherte Dienstplan-Datei. Bitte eine Datei „Dienstplan … - Version ….json“ wählen.",
  mismatch: "Die Datei ist beschädigt und kann nicht geladen werden.",
  no_schedule: "Die Datei enthält keinen Dienstplan.",
  references: "Die Datei enthält Dienste, die nicht zu ihrem Monat oder ihrer Station passen.",
  policy: "Die Datei stammt aus einer anderen Version der Anwendung.",
  check: "Die Datei stammt aus einer anderen Version der Anwendung.",
};

/** Review an uploaded plan file (form field `plan`); a rejected file leaves the current review unchanged. */
export function importPlan(files: FormData) {
  return request<ScheduleReview>("POST", "/review/import-plan", {
    body: files,
    invalid: IMPORT_PROBLEMS.malformed,
    problems: IMPORT_PROBLEMS,
  });
}

const HISTORY_PROBLEMS: Record<BundleProblem | HistoryProblem, string> = {
  ...IMPORT_PROBLEMS,
  malformed: "Das ist keine gespeicherte Dienstplan-Datei.",
  wrong_month: "Das ist nicht der Dienstplan des Vormonats.",
  not_accepted: "Dieser Dienstplan hält nicht alle Regeln ein und kann nicht als Vormonat dienen.",
  foreign: "Dieser Dienstplan gehört zu einer anderen Station oder anderen Mitarbeitern.",
};

/** The month before loaded as this month's history, or `null` without one. */
export function getHistory(month: string) {
  return request<HistorySummary | null>("GET", "/history", { params: monthQuery(month) });
}

/** Load a saved plan file of the month before (form field `plan`) as this month's history; checked by the backend. */
export function putHistory(month: string, files: FormData) {
  return request<HistorySummary>("PUT", "/history", {
    params: monthQuery(month),
    body: files,
    invalid: HISTORY_PROBLEMS.malformed,
    problems: HISTORY_PROBLEMS,
  });
}

/** Stop using a month before as this month's history. */
export function deleteHistory(month: string) {
  return request<void>("DELETE", "/history", { params: monthQuery(month) });
}

/** The schedule under review as one plan file with the API's attachment headers, or `null` without a review. */
export async function getPlanFile(): Promise<Response | null> {
  try {
    return await send("GET", "/review/plan");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function isApiHealthy() {
  try {
    const response = await fetch(`${API_URL}/status`, { signal: AbortSignal.timeout(5_000) });
    return response.ok && (await response.json()).status === "healthy";
  } catch {
    return false;
  }
}
