"use server";

import { startGeneration } from "@/lib/api";
import { writeResult } from "@/lib/write-result";

/** Start a generation with the backend's fixed solver time; success means the input is valid and solving began. */
export async function generate(month: string, stationIds: number[]) {
  return writeResult(() => startGeneration(month, stationIds), "/generation");
}
