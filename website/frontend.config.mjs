import path from "node:path";
const root = path.resolve(import.meta.dirname, "..");
const sharedState = path.join(root, "static/js/app-state.js");
const websiteState = path.join(root, "website/static/js/app-state.js");
export default {
  entryPoints: { app: "website/static/js/main.js", "app-styles": "website/static/css/app.css" },
  banner: { js: "/* fishing-logbook-website */" },
  inject: [path.join(root, "website/static/js/runtime.js")],
  plugins: [{
    name: "website-state-adapter",
    setup(build) {
      build.onResolve({ filter: /app-state\.js$/ }, (args) => {
        if (args.importer === websiteState) return;
        if (path.resolve(args.resolveDir, args.path) === sharedState) return { path: websiteState };
      });
    },
  }],
};
