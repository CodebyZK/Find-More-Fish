const { test, expect } = require("@playwright/test");

test("login keeps the destination and supports keyboard sign-in", async ({ page }) => {
  await page.goto("/login?next=/map");
  await expect(page).toHaveTitle("Sign in · Find More Fish");
  await expect(page.getByRole("heading", { name: "Welcome back.", exact: true })).toBeVisible();
  const signIn = page.getByRole("link", { name: "Continue with GitLab", exact: true });
  expect(new URL(await signIn.getAttribute("href"), page.url()).searchParams.get("next")).toBe("/map");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Find More Fish home" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(signIn).toBeFocused();
  expect(await signIn.evaluate(element => getComputedStyle(element).outlineStyle)).not.toBe("none");
});

test("login fits desktop, tablet, and mobile viewports", async ({ page }, testInfo) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 1024, height: 768 },
    { width: 760, height: 900 },
    { width: 390, height: 844 },
    { width: 320, height: 760 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/login");
    const signIn = page.getByRole("link", { name: "Continue with GitLab", exact: true });
    await expect(signIn).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    const button = await signIn.boundingBox();
    expect(button.height).toBeGreaterThanOrEqual(44);
    expect(button.x).toBeGreaterThanOrEqual(16);
    expect(button.x + button.width).toBeLessThanOrEqual(viewport.width - 16);
    if (viewport.width === 1440 || viewport.width === 390) {
      await page.screenshot({ path: testInfo.outputPath(viewport.width === 1440 ? "login-desktop.png" : "login-mobile.png"), fullPage: true });
    }
  }
  expect(errors).toEqual([]);
});

test("a sign-in error remains readable without blocking a retry", async ({ page }) => {
  const message = "Sign-in could not be verified. Please try again.";
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login?next=/gear&error=" + encodeURIComponent(message));
  await expect(page.getByRole("alert")).toHaveText(message);
  const signIn = page.getByRole("link", { name: "Continue with GitLab", exact: true });
  await expect(signIn).toBeVisible();
  expect(new URL(await signIn.getAttribute("href"), page.url()).searchParams.get("next")).toBe("/gear");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});
