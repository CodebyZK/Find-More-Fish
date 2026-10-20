const { test, expect } = require("@playwright/test");
async function signIn(context, userId) {
  const start = await context.request.get("/auth/gitlab?next=/trips", { maxRedirects: 0 });
  const state = new URL(start.headers().location).searchParams.get("state");
  const finish = await context.request.get("/auth/gitlab/callback?state=" + state + "&code=" + userId, { maxRedirects: 0 });
  expect(finish.status()).toBe(302);
}
async function saveTrip(context, id, title) {
  const snapshot = await context.request.get("/api/logbook");
  const document = await snapshot.json();
  document.trips.push({ id, title, catches: [] });
  const csrf = await (await context.request.get("/api/csrf-token")).json();
  expect((await context.request.put("/api/logbook", { data: document, headers: { "X-CSRF-Token": csrf.csrfToken, "If-Match": snapshot.headers().etag } })).status()).toBe(200);
  return document;
}
test("anonymous visitors see the website login and cannot read private APIs", async ({ page, request }) => {
  await page.goto("/trips");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("link", { name: /Continue with GitLab/ })).toBeVisible();
  expect((await request.get("/api/logbook")).status()).toBe(401);
  expect((await request.get("/website/static/css/login.css")).status()).toBe(200);
});
test("account switching keeps server data separate and never caches the document", async ({ page, context }) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await signIn(context, 101);
  const alice = await saveTrip(context, "alice-private", "Alice private fishing trip");
  await page.addInitScript(document => localStorage.setItem("fishing-logbook-v2", JSON.stringify(document)), alice);
  await page.goto("/trips");
  await expect(page.locator(".account-name")).toHaveText("User 101");
  await expect(page.locator("#tripTable")).toContainText("Alice private fishing trip");
  expect(await page.evaluate(() => localStorage.getItem("fishing-logbook-v2"))).toBeNull();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login/);
  expect((await context.request.get("/api/logbook")).status()).toBe(401);
  await signIn(context, 202);
  await page.goto("/trips");
  await expect(page.locator(".account-name")).toHaveText("User 202");
  await expect(page.locator("#emptyState")).toBeVisible();
  expect(await page.locator("body").textContent()).not.toContain("Alice private fishing trip");
  expect(await page.evaluate(() => localStorage.getItem("fishing-logbook-v2"))).toBeNull();
  expect(errors).toEqual([]);
});
test("unavailable server data cannot install a previous account's cached logbook", async ({ page, context }) => {
  await signIn(context, 303);
  const cached = await (await context.request.get("/api/logbook")).json();
  cached.trips = [{ id: "stale-private", title: "Never display cached private trip" }];
  await page.addInitScript(document => localStorage.setItem("fishing-logbook-v2", JSON.stringify(document)), cached);
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/logbook", route => route.fulfill({ status: 503, json: { error: "unavailable" } }));
  await page.goto("/trips");
  await expect.poll(() => errors.some(error => error.includes("Could not load your logbook"))).toBe(true);
  expect(await page.locator("body").textContent()).not.toContain("Never display cached private trip");
  expect(await page.evaluate(() => localStorage.getItem("fishing-logbook-v2"))).toBeNull();
});
test("an expired session returns to login when a shared settings control saves", async ({ page, context }) => {
  await signIn(context, 404);
  await page.goto("/settings");
  await page.getByRole("button", { name: "Map Pins", exact: true }).click();
  await context.clearCookies();
  await page.locator('[data-species-map-color="Largemouth Bass"]').evaluate(input => {
    input.value = "#123456";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await expect(page).toHaveURL(/\/login/);
});
