## Purpose
SvelteKit app root: global styles, HTML shell, ambient types, plus the `lib/` and `routes/` trees.

## Contents
- `app.html` — HTML shell.
- `app.css` — global stylesheet: design tokens (colors, spacing, typography) and base styles for the whole app, including the `button` and `a` element resets (every link here is a nav row or card with its own styling, so none want the browser's blue underline).
- `app.d.ts` — SvelteKit ambient type declarations.
- `lib/` — stores, API layer, components, screen logic (see its SPEC.md).
- `routes/` — the app's screens (see its SPEC.md).

## Inputs / Outputs
Compiled by Vite/SvelteKit into the static build.

## Conventions & Constraints
- Styling is plain CSS in `app.css` + component `<style>` blocks; no CSS framework.

## Open Questions
- None.
