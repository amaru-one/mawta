# Mawta Nítido — component library

This library implements the Índigo palette from _mawta-nitido-design-system.pdf_, version 1, October 2026. It is the foundation for a subsequent screen migration. Production routes do not import it yet. There is no gallery, preview route, or Storybook.

## Start using the library

Import components from `$lib/design-system`. Mount one `DesignSystem` wrapper around the new UI. It loads Plus Jakarta Sans (400–800) from the PDF’s Google Fonts URL and supplies scoped typography, resets, and `--mw-*` tokens. The wrapper uses a white content surface. Apply `--mw-surface-page` only to fixed bands or the surrounding page when migrating the shell.

```svelte
<script lang="ts">
	import { DesignSystem, Field, Button } from '$lib/design-system';
	let name = $state('');
</script>

<DesignSystem>
	<form
		onsubmit={(event) => {
			event.preventDefault(); /* Save in the caller. */
		}}
	>
		<Field label="Nombre" name="name" bind:value={name} required />
		<Button type="submit" variant="primary">Guardar experiencia</Button>
	</form>
</DesignSystem>
```

Every component must remain a descendant of `DesignSystem`. Native dialog and popover top-layer rendering preserves this ancestry and its theme; do not move their nodes into `document.body`. Importing the module does not alter document-wide tokens. Existing Aurora classes and components remain separate.

## Component contracts

All components use Svelte 5. Values bind through `bind:value`, checkboxes through `bind:checked`, and dialogs through `bind:open`. Data and callbacks come from the caller. Components do not import application stores, API DTOs, routing, authentication, or business rules. Exported shared types describe options, capabilities, statuses, toast messages, and variants; use Svelte’s `ComponentProps<typeof Component>` for complete prop types.

| Component                     | Contract                                                                                                                                                                                                                                                                                                                      |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Button`                      | Required content snippet; `variant="primary"                                                                                                                                                                                                                                                                                  | "secondary"`(secondary default),`block`, optional `icon`/`iconPosition`, `loading`, and native button attributes/events. Defaults to `type="button"`. Loading disables activation and sets `aria-busy`. |
| `ButtonRow`                   | Content snippet; shares available width between buttons and wraps on small screens.                                                                                                                                                                                                                                           |
| `Action`                      | Content snippet, optional icon, `variant="neutral"                                                                                                                                                                                                                                                                            | "main"                                                                                                                                                                                                  | "remove"                                                                                                                                                                                                                                                                                                                                                                                                                              | "link"`. Supply `href`for an anchor or`onclick` for a button. Disabled/loading links lose their destination; removal actions move to the trailing edge. |
| `IconButton` / `Icon`         | Typed icon name. IconButton requires an accessible `label`, supports native button props, and optionally `outlined`. Icons are decorative; meaningful icons require surrounding text or a labeled control.                                                                                                                    |
| `Text`                        | Content snippet, `variant` from the PDF typography table, optional semantic `as` (`p` by default). Choosing a visual title does not automatically choose a heading level.                                                                                                                                                     |
| `Card`                        | Content and optional `actions` snippets. One decision per card. Actions are separated from the body by a rule.                                                                                                                                                                                                                |
| `Context`                     | Content snippet on the context surface.                                                                                                                                                                                                                                                                                       |
| `Field`                       | Required visible `label`; `kind="input"                                                                                                                                                                                                                                                                                       | "textarea"                                                                                                                                                                                              | "select"`, bindable `value`, select `options`, `help`, `error`, `large`, optional `labelAction`snippet. Supports form attributes, native events, generated or explicit IDs, and description/error associations.`type`applies only to inputs;`rows`only to textareas. Options have string values. Numeric inputs bind numbers; clearing them yields`null`, matching the installed Svelte runtime. An omitted initial value is allowed. |
| `Checkbox`                    | Label, optional description, bindable checked state, native checkbox attributes. The whole row is a native checkbox label.                                                                                                                                                                                                    |
| `CheckboxGroup`               | Label, options (`value`, full `label`, optional `description`/`disabled`), bindable string-array value, optional `name`, help/error, and `onchange(nextValues)`. Native checkboxes preserve keyboard and form semantics rather than imitating them with pressed buttons.                                                      |
| `Segmented`                   | Accessible group label, two to four short options, bindable string value, optional `name`, disabled state, and `onchange(nextValue)`. Uses pressed buttons: Tab moves between options, Space/Enter selects. Use Field/select for longer lists or labels.                                                                      |
| `CoverageMeter`               | Capabilities (`id`, short `label`, `covered`) and optional heading. Missing capabilities are written out; each segment has a screen-reader state. Empty arrays display “Sin capacidades”.                                                                                                                                     |
| `StatusList`                  | Items with `id`, `name`, `status="done"                                                                                                                                                                                                                                                                                       | "due"                                                                                                                                                                                                   | "waiting"`, explicit status `label`, and optional detail. Labels remain caller-controlled.                                                                                                                                                                                                                                                                                                                                            |
| `Notice`                      | Content, `variant="info"                                                                                                                                                                                                                                                                                                      | "attention"                                                                                                                                                                                             | "danger"`, optional icon. `live` opts into status/alert announcements for newly appearing messages. Static notices do not repeatedly announce.                                                                                                                                                                                                                                                                                        |
| `Toast`                       | Nullable `message` with unique `id`, message text, optional action and label, optional duration override; required `ondismiss(id)`. Caller clears only the matching message. Defaults: 2 seconds, or 7 seconds with an action. Replacement/unmount cleans up timers. Uses a manual popover so fixed ancestors cannot clip it. |
| `TopBar`                      | Name, school, initials; optional back, identity, and notifications callbacks, unread count, and extra actions snippet. No dependency on teacher stores or navigation history.                                                                                                                                                 |
| `StepNav`                     | Current title, **zero-based** index, total, optional noun and previous/next callbacks. Boundary buttons are disabled.                                                                                                                                                                                                         |
| `SessionRow`                  | Valid calendar date `YYYY-MM-DD`, title, optional topics, evidence (`name`, optional `href`), and action snippet. `off` displays the crossed-out date/title and non-teaching-day detail. Date labels use `es-PE` without shifting across host time zones.                                                                     |
| `Dialog`                      | Bindable open state, title, optional description/body/actions and close callback. Uses native modal focus isolation and Escape dismissal; restores focus to the opener.                                                                                                                                                       |
| `ConfirmDialog`               | Bindable open state, title, description, confirm label, confirmation and optional cancellation callbacks. Closes before invoking the selected action. Business operations stay in the caller.                                                                                                                                 |
| `EmptyState` / `LoadingState` | Empty-state title plus optional description/icon/actions; loading-state accessible label (defaults to “Cargando…”).                                                                                                                                                                                                           |

## Visual rules and source decisions

Use one primary button per screen. Buttons and fields have minimum 48px targets; text/icon actions have minimum 40px targets. Put the reason for a disabled button in nearby help text and connect it with `aria-describedby`.

Use rectangular buttons, solid accent fills, full competency names in selection rows, and written statuses. Do not reintroduce chips, gradients, monospace metadata, or colored card sidebars. Copy is in Peruvian Spanish; library documentation is in English.

The PDF’s typography table is authoritative (in particular, heading uses weight 700). The PDF names but does not numerically define shadows: card/action/raised shadow values come from the accompanying Nítido planning HTML prototype. Circular step navigation follows the explicit TopBar/StepNav example. Native checkboxes are the intentional semantic equivalent of the PDF’s visual selection rows.

The `--mw-` prefix maps one-to-one to the PDF token names. Colors, typography sizes/line heights, spacing, radii, and shadows live in `styles.css`. Focus is a 2px ring with 2px offset. Loading motion respects `prefers-reduced-motion`.

## Migration handoff

| Current implementation                             | Future replacement                                                         |
| -------------------------------------------------- | -------------------------------------------------------------------------- |
| `app.css` palette and global primitives            | Opt-in DesignSystem tokens; migrate the shell in the screen-refactor phase |
| `.btn-block`, `.btn-dark`, `.btn-light`, `.pill-*` | Button / ButtonRow                                                         |
| `.mini`, per-card action buttons                   | Action in Card’s actions snippet                                           |
| `.field`, title inputs, situation editors          | Field with label, help, and error props                                    |
| Checkbox rows and bespoke segmented selectors      | CheckboxGroup / Segmented                                                  |
| Coverage bars and status markers                   | CoverageMeter / StatusList                                                 |
| Inline notices and empty/loading paragraphs        | Notice / EmptyState / LoadingState                                         |
| Existing store-driven TopBar and Toast             | New components supplied by app-owned adapters                              |
| Competency navigation and session rows             | StepNav / SessionRow                                                       |
| Existing confirmation and score dialogs            | Dialog / ConfirmDialog with domain-specific form snippets                  |

Do not alias old Aurora variables to the new tokens: several colors have changed roles. Adapt route data into the library’s small view types during the second phase. Existing grading and recording components need their own migration decisions; this library does not change their behavior.

## Verification

```sh
bun install --frozen-lockfile
bunx playwright install chromium webkit
bun run check
bun eslint .
bun run test:components
bun run build
```

Component tests use isolated Svelte fixtures in Chromium and WebKit, including legacy CSS to check coexistence. Fixtures are not application routes and do not call the backend. CI installs both browser engines and runs the same suite.
