import { protectedFetch, storageKey } from "../../../static/js/app-config.js";
try { globalThis.localStorage.removeItem(storageKey); } catch { /* Storage may be disabled. */ }
document.querySelector("#logoutButton")?.addEventListener("click", async () => {
  try {
    const response = await protectedFetch("/logout", { method: "POST" });
    if (!response.ok) throw new Error("Could not sign out");
    window.location.assign("/login");
  } catch (error) {
    alert(error.message || "Could not sign out. Please try again.");
  }
});
