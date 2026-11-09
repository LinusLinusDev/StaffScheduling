"use server";

import { importPlan } from "@/lib/api";
import { writeResult } from "@/lib/write-result";

/** Load a saved plan file (form field `plan`); success means the backend validated and re-checked it. */
export async function loadPlan(files: FormData) {
  // The page reloads the review itself, so the large review is not sent back to the browser.
  return writeResult(async () => {
    await importPlan(files);
  }, "/review");
}
