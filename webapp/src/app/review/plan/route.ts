import { getPlanFile } from "@/lib/api";

/** Download the schedule under review as one plan file, named by its month, year and version; the API stays server-side. */
export async function GET() {
  try {
    const file = await getPlanFile();
    if (!file) return new Response("Kein Dienstplan zum Speichern.", { status: 404 });
    const headers = [...file.headers].filter(([key]) => key === "content-type" || key === "content-disposition");
    return new Response(file.body, { headers });
  } catch (error) {
    return new Response((error as Error).message, { status: 503 });
  }
}
