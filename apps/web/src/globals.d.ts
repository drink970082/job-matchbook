// Ambient declaration so a bare `tsc --noEmit` accepts side-effect CSS imports
// (e.g. `import "./globals.css"` in the root layout). Next's own build handles CSS
// via webpack, but the standalone TS compiler has no loader for it — this keeps
// editor/CLI type-checks clean and matching `next build`. Plain `*.css` only;
// CSS Modules (`*.module.css`) keep Next's typed default export.
declare module "*.css";
