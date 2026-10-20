// esbuild injects these lexical adapters into the website bundle only.
// The browser globals and the shared client sources remain unchanged.
import { storageKey } from "../../../static/js/app-config.js";
export const localStorage = {
  getItem(key) { return String(key) === storageKey ? null : globalThis.localStorage.getItem(key); },
  setItem(key, value) { if (String(key) !== storageKey) globalThis.localStorage.setItem(key, value); },
  removeItem(key) { globalThis.localStorage.removeItem(key); },
};
export async function fetch(input, options) {
  const response = await globalThis.fetch(input, options);
  const url = new URL(typeof input === "string" || input instanceof URL ? input : input.url, globalThis.location.href);
  if (url.origin === globalThis.location.origin && response.status === 401) {
    globalThis.location.assign("/login");
    throw new Error("Sign in to access your logbook.");
  }
  return response;
}
