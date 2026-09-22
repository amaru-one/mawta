## Purpose
The SvelteKit app root: the HTML shell, the global stylesheet, ambient types, and the `lib/` and `routes/` trees.

## Contents
- `app.html` — the HTML shell: `lang="en"`, a `width=device-width, initial-scale=1` viewport meta, a `text-scale` meta, the two SvelteKit placeholders, and `data-sveltekit-preload-data="hover"` on the body. The favicon link is added by `routes/+layout.svelte`, which also overrides the viewport meta with a `viewport-fit=cover` one.
- `app.css` — the design system, in one light theme with no `prefers-color-scheme` block and no `[data-theme]` selectors:
  - **Tokens on `:root`.** Surfaces and borders (`--surface-1` `#e8eaf7`, `--surface-2` `#ffffff`, `--border`, `--border-strong`); text (`--text-primary` `#4a5fd6`, `--text-secondary`, `--text-muted`, `--text-faint` for the unset member of a set, plus `--text-success`, `--text-danger`, `--text-warning`); fills (`--ink-deep` `#2c3178`, `--fill-primary`, `--fill-success`, `--fill-danger`, `--fill-warning`, `--fill-tier-c`); the assistant accent (`--fill-accent`, `--text-accent`, `--bg-accent`); the aurora set (`--aurora-1`, `--aurora-2`, `--aurora-3`, `--aurora-deep`, `--aurora-tint`, `--hair`); gradients (`--gradient-action` for what you touch, `--gradient-tile` for icon squares, `--shadow-action`); foregrounds on fills (`--on-primary` and its siblings, `--on-tier-c`); type (`--font-sans`, `--font-mono`); an 8px spacing scale (`--space-xs` through `--space-3xl`); radii (`--radius-xs` through `--radius-lg`); tinted shadows (`--shadow-sm`, `--shadow-md`, `--shadow-lg`, `--shadow-accent`); and `--shell-width` at 480px. The neutral ladder sits on the aurora hue, and hierarchy is made by dropping chroma rather than by darkening — `--text-secondary` is the deeper of the two body tones.
  - **Element resets.** `border-box` everywhere, the body on `--surface-1` in `--text-primary` at 16px/1.5 with `-webkit-tap-highlight-color: transparent`, `button` stripped to inherit its font, and `a` inheriting colour with no underline, since every link in the app is a nav row or a card with its own styling.
  - **Layout primitives and shared classes.** `.app-shell` (the centred `--shell-width` column on `--surface-2`), `.topbar`, `.avatar`, `.body`, `.eyebrow`, `.screen-title` and `.screen-sub`, `.card`, `.stat`, `.context-card`, `.grid3`, the fully rounded buttons and pills (`.btn-dark`, `.btn-light`, `.btn-block` and `.btn-block.btn-primary`, `.pill-dark`, `.pill-light`), `.search` with `.search-wrap`, `.icon-tile`, `.ic` (the `1em` icon base `Icon.svelte` renders into), and the atoms `.dot`, `.divider`, `.row`, `.grow` (`flex:1; min-width:0`, the overflow idiom), `.lvl` and `.meta`. `.pressable` carries the shared press feedback — a 150ms transition and a `scale(0.95)` on `:active`, with `user-select: none` and `touch-action: manipulation`.
- `app.d.ts` — the SvelteKit ambient declarations, with the five `App` interfaces left commented out.
- `lib/` — stores, the API layer, components and screen logic (see its SPEC.md).
- `routes/` — the app's screens (see its SPEC.md).

## Inputs / Outputs
Compiled by Vite and SvelteKit into the static build in `../build/`.

## Conventions & Constraints
- Styling is plain CSS: tokens and shared primitives in `app.css`, everything else in component `<style>` blocks. There is no CSS framework.
- Components read tokens rather than literal colours, so a token swap moves the whole palette.

## Open Questions
- `lib/assets/favicon.svg` is still the default SvelteKit logo rather than a Yanai mark.
