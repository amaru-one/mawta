# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**yanay-ui** — A teacher's in-class lesson companion for tracking attendance, participation, and voice observations. Built with SvelteKit 5 + TypeScript (strict mode), IndexedDB persistence, no backend.

Uses **Bun** as the package manager and runtime for fast install/build times.

## Build & Development

```bash
bun dev          # Start Vite dev server (http://localhost:5173)
bun run build    # Production build
bun run check    # Run svelte-check + TypeScript compilation
bun run check:watch  # Watch mode for type checking
```

Type checking must pass before committing. Use `bun run check:watch` during development.

## Code Style

- **TypeScript**: strict mode enforced (`noImplicitAny`, `strict: true`)
- **Imports**: Use `$lib/` alias for imports from `src/lib/` (configured in SvelteKit)
- **Formatting**: Prettier (configured in `.prettierrc`); runs automatically on edits
- **Linting**: ESLint for TypeScript/Svelte; runs before commits

## Design System

**Color Palette**: All colors must come from `src/app.css` CSS variables. **Never use hardcoded hex colors in components.**

**Hybrid Palette** (Pure Grayscale + High Contrast Strategy):
Combines the sophistication of full grayscale with the minimalism of high contrast.

**Core 7 Gray Tones** (strategically selected white → black):
- `--white`: #ffffff (pure white)
- `--gray-100`: #f5f5f5 (near-white for subtle backgrounds)
- `--gray-200`: #e0e0e0 (light gray for secondary backgrounds)
- `--gray-400`: #b0b0b0 (medium gray for borders/secondary text)
- `--gray-600`: #606060 (medium-dark gray for text)
- `--gray-800`: #333333 (dark gray for strong elements)
- `--black`: #000000 (pure black)

**Extended Palette** (9 tones available for component flexibility):
- `--gray-50`, `--gray-300`, `--gray-500`, `--gray-700`, `--gray-900`

**Semantic colors** (pure grayscale, high contrast priority):
- `--primary`: Black (#000000) - strong visual hierarchy
- `--success`: Dark gray (#333333) - positive actions
- `--warning`: Medium gray (#606060) - neutral warnings
- `--danger`: Black (#000000) - destructive actions

**Action colors**:
- `--action-save`: Black (#000000) / dark gray hover (#333333)
- `--action-delete`: Black (#000000) / dark gray hover (#333333)
- `--action-complete`: Dark gray (#333333) / black hover (#000000)

**Design philosophy**:
- Pure grayscale (white to black only) - no colors
- High contrast strategy (black/dark gray preferred over mid-tones)
- Maximum accessibility (WCAG AAA compliant)
- Professional, timeless, minimalist aesthetic
- Works perfectly for printing and colorblind users
- Flexible hierarchy through tonal variation

## Git Workflow

**Commit style:**
- Descriptive, present-tense commit messages (e.g., "add voice note playback")
- **Do NOT include `Co-Authored-By: Claude` footer** — commits are by you, not Claude
- Pre-commit hook runs linting and type check; commit will fail if either fails

**Branch naming:** Use descriptive names (e.g., `feature/voice-tags`, `fix/attendance-sync`)

## SvelteKit Conventions

- **Routes**: File-based routing in `src/routes/`
- **Layout nesting**: Use `+layout.svelte` for nested layouts
- **Server logic**: Move backend logic to `+page.server.ts` or `+layout.server.ts` (though this project has no backend)
- **Stores**: Svelte stores in `src/lib/stores.ts` for shared state (currentSession, students, entries, notes, assessments)
- **Components**: Colocate in `src/lib/components/`
- **Types**: Centralize in `src/lib/types.ts` (Course, Student, Session, Block, Assessment, Entry, Note)

## IndexedDB & Persistence

- All data stored in IndexedDB (`src/lib/db.ts`)
- No async/await errors are shown to users; failures retry silently
- Mutations go through `src/lib/lesson.ts` orchestration layer
- Use typed store subscriptions; avoid direct DB access outside `db.ts`

## Testing

No test framework configured yet. When adding tests, run them with a clear command in this file.

## Performance Targets

- First paint: < 800ms cold start
- Full attendance pass (28 students): 60 seconds
- Tap response: instant (no lag)

## Non-Goals

- No scoring or grades on this screen
- No authentication
- No dark mode, settings, or onboarding
- No export or reporting

Refer to README.md for detailed feature list and architecture.
