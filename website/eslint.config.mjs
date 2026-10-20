import globals from "globals";
import shared from "../eslint.config.mjs";
export default [
  ...shared.flatMap(config => config.files?.includes("static/js/**/*.js") ? [{ ...config, files: ["website/static/js/**/*.js"] }] : []),
  { files: ["website/**/*.mjs"], languageOptions: { ecmaVersion: 2022, sourceType: "module", globals: { ...globals.node, ...globals.browser } }, rules: { "no-undef": "error", "no-unused-vars": ["error", { args: "none", caughtErrors: "none" }] } },
  { files: ["website/**/*.cjs", "website/tests/e2e/*.js"], languageOptions: { sourceType: "commonjs", globals: { ...globals.node, ...globals.browser } }, rules: { "no-undef": "error" } },
];
