## Purpose
SvelteKit app root: global styles, HTML shell, ambient types, plus the `lib/` and `routes/` trees.

## Contents
- `app.html` — HTML shell.
- `app.css` — global stylesheet: design tokens (colors, spacing, typography) and base styles for the whole app.
- `app.d.ts` — SvelteKit ambient type declarations.
- `lib/` — stores, API layer, components, screen logic (see its SPEC.md).
- `routes/` — the six screens (see its SPEC.md).

## Inputs / Outputs
Compiled by Vite/SvelteKit into the static build.

## Conventions & Constraints
- Styling is plain CSS in `app.css` + component `<style>` blocks; no CSS framework.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
