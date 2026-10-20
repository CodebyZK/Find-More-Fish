const os = require("node:os");
const path = require("node:path");
const { defineConfig, devices } = require("@playwright/test");
const baseURL = "http://127.0.0.1:4174";
module.exports = defineConfig({
  testDir: "./tests/e2e", workers: 1, retries: 0,
  outputDir: path.resolve(process.env.PW_ARTIFACTS_DIR || path.join(os.tmpdir(), "fishing-logbook-website-playwright")),
  reporter: "list",
  use: { baseURL, trace: "retain-on-failure", screenshot: "only-on-failure", ...devices["Desktop Chrome"], channel: process.env.PLAYWRIGHT_CHANNEL || undefined },
  webServer: {
    cwd: path.resolve(__dirname, ".."),
    command: "node website/tests/start-server.mjs",
    url: baseURL + "/healthz",
    // Keep the test server independent of the normal app's PORT environment.
    env: { PORT: new URL(baseURL).port },
    reuseExistingServer: false,
    timeout: 30000,
  },
});
