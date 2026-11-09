"use server";

import { importReview } from "@/lib/api";
import { writeResult } from "@/lib/write-result";

/** Review an uploaded `input`/`result` pair; success means the backend validated and re-checked it. */
export async function importFiles(files: FormData) {
  // The page reloads the review itself, so the large review is not sent back to the browser.
  return writeResult(async () => {
    await importReview(files);
  }, "/review");
}
