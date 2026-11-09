"use server";

import { deleteHistory, putHistory, startGeneration } from "@/lib/api";
import { writeResult } from "@/lib/write-result";

/** Start a generation with the backend's fixed solver time; success means the input is valid and solving began. */
export async function generate(month: string, stationIds: number[]) {
  return writeResult(() => startGeneration(month, stationIds), "/generation");
}

/** Load a saved plan file of the month before as the month's history; success means the backend accepted it. */
export async function loadHistory(month: string, files: FormData) {
  return writeResult(async () => {
    await putHistory(month, files);
  }, "/generation");
}

/** Stop using the month before as the month's history. */
export async function removeHistory(month: string) {
  return writeResult(() => deleteHistory(month), "/generation");
}
