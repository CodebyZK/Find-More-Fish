import assert from "node:assert/strict";
import { installBrowserEnv, okJson, setFetch } from "../../tests/helpers/browser-env.mjs";
installBrowserEnv();
const { defaults } = await import("../../static/js/app-defaults.js");
const state = await import("../../static/js/app-state.js");
const websiteState = await import("../static/js/app-state.js");
const runtime = await import("../static/js/runtime.js");
globalThis.localStorage.setItem("fishing-logbook-v2", JSON.stringify(defaults));
assert.equal(runtime.localStorage.getItem("fishing-logbook-v2"), null);
runtime.localStorage.setItem("fishing-logbook-v2", "must not persist");
assert.deepEqual(JSON.parse(globalThis.localStorage.getItem("fishing-logbook-v2")), defaults);
runtime.localStorage.setItem("map-preference", "true");
assert.equal(globalThis.localStorage.getItem("map-preference"), "true");
for (const failedRead of [
  async () => { throw new Error("unavailable"); },
  async () => okJson({}, { status: 503 }),
  async () => okJson({ schemaVersion: 1 }, { headers: { ETag: '"99"' } }),
]) {
  state.setLogbookRevision('"stale"');
  setFetch(failedRead);
  await assert.rejects(websiteState.loadState());
  assert.equal(state.logbookRevision, "");
}
setFetch(async () => okJson(defaults, { headers: { ETag: '"7"' } }));
assert.deepEqual(await websiteState.loadState(), defaults);
assert.equal(state.logbookRevision, '"7"');
