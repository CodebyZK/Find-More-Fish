const os = require("node:os");
const path = require("node:path");
const { defineConfig, devices } = require("@playwright/test");
module.exports = defineConfig({
  testDir: "./tests/e2e", workers: 1, retries: 0,
  outputDir: path.join(os.tmpdir(), "fishing-logbook-website-playwright"),
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:4174", ...devices["Desktop Chrome"], channel: process.env.PLAYWRIGHT_CHANNEL || undefined },
  webServer: { cwd: path.resolve(__dirname, ".."), command: "node website/tests/start-server.mjs", url: "http://127.0.0.1:4174/healthz", reuseExistingServer: false, timeout: 30000 },
});
