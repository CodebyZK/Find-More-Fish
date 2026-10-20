// Share all state and UI helpers; only the startup data source differs.
export * from "../../../static/js/app-state.js";
import { setLogbookRevision } from "../../../static/js/app-state.js";
import { validateState } from "../../../static/js/app-normalization.js";
import { fetch } from "./runtime.js";
export async function loadState() {
  setLogbookRevision("");
  const response = await fetch("/api/logbook");
  if (!response.ok) throw new Error("Could not load your logbook from the server.");
  const document = validateState(await response.json());
  setLogbookRevision(response.headers.get("ETag") || "");
  return document;
}
