# Mawta Nítido — component library

Mawta uses the Índigo palette from `mawta-nitido-design-system.pdf` (October 2026). All production screens share this library. The application remains a responsive, centered column with a maximum width of 480px; there is no gallery route or Storybook.

## Theme and ownership

Import components from `$lib/design-system`. The root layout mounts one `DesignSystem` around the application, including loading states, dialogs, and toasts. The wrapper supplies Plus Jakarta Sans (400–800), scoped resets, and `--mw-*` tokens. The surrounding page uses `--mw-surface-page`; the application column uses `--mw-surface-card`.

Native dialog and popover top-layer rendering preserves theme ancestry. Do not move overlays into `document.body`. Global `app.css` contains document resets; `lib/styles/application.css` owns application geometry and domain layout. Production code has no Aurora token aliases.

Use solid surfaces, visible field labels and borders, text actions within cards, and status words alongside markers. Minimum text size is 11px. Buttons and fields have 48px targets; compact actions have at least 40px targets. Use a single primary action per screen. Follow the PDF's reduced-motion and focus-ring rules.

## Component contracts

Components use Svelte 5. Values bind through `bind:value`, checkboxes through `bind:checked`, and dialogs/disclosures through `bind:open`. Shared components accept data and callbacks; they do not import API DTOs, application stores, authentication, or routing. Use `ComponentProps<typeof Component>` for full prop types.

| Component                              | Contract                                                                                                                                                                                                                                                               |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Button`                               | Content snippet, primary/secondary variant, block layout, optional icon, loading state, native button attributes. Defaults to `type="button"`. `href`, `target`, and `rel` render native links. Disabled/loading links have no destination and cannot activate.        |
| `Action`                               | Text action with neutral/main/remove/link variants, optional icon, native destination or callback.                                                                                                                                                                     |
| `IconButton`                           | Required accessible `label` and icon. Supports native link destinations and disabled state.                                                                                                                                                                            |
| `Field`                                | Required label; input, textarea, or select; bindable value; help/error text; optional label action. Select choices come from `options` or a child snippet. `bind:control` exposes the native input/textarea/select for focus and blur. Attachments reach that control. |
| `Checkbox`, `CheckboxGroup`            | Native checkbox behavior, visible label or content, descriptions, and bindable selection.                                                                                                                                                                              |
| `Segmented`                            | Named option group with pressed state, optional disabled choices, bindable value, and change callback.                                                                                                                                                                 |
| `Card`, `Context`                      | Content surfaces. Cards provide separate body/actions snippets. Domain layouts belong inside the content.                                                                                                                                                              |
| `ListRow`                              | Native link with content, optional trailing snippet, and chevron. Do not place other interactive controls inside it.                                                                                                                                                   |
| `Disclosure`                           | Summary/content snippets, bindable open state, optional toggle callback. Native button activation with `aria-expanded` and `aria-controls`; hidden content preserves editing state.                                                                                    |
| `TopBar`                               | Teacher identity or title, optional native back/profile/notification destinations, callbacks, notification count, actions and status snippets. The application adapter owns history fallback, stores, and haptics.                                                     |
| `StepNav`                              | Title, zero-based index, total, previous/next callbacks, disabled end states.                                                                                                                                                                                          |
| `CoverageMeter`, `StatusList`          | Coverage/status data rendered with labels; color is supplementary. Callers determine business meaning and accepted-criterion coverage.                                                                                                                                 |
| `SessionRow`                           | ISO calendar date, title, topics, evidence reference, off-day state, actions. Optional editor snippet replaces the read view without changing date placement.                                                                                                          |
| `Notice`, `LoadingState`, `EmptyState` | Shared feedback states. Use danger notices for errors and attention notices for nonblocking warnings.                                                                                                                                                                  |
| `Dialog`, `ConfirmDialog`              | Native modal dialogs, keyboard focus containment/restoration, accessible title, and cancellation callbacks.                                                                                                                                                            |
| `Toast`                                | Message identity, text, optional action and duration; dismiss callback receives the message ID. Owns the only expiry timer. Defaults: 2 seconds normally, 7 seconds with an action.                                                                                    |
| `Text`, `Icon`, `ButtonRow`            | Typography hierarchy, trusted inline glyphs, and wrapping action layout.                                                                                                                                                                                               |

```svelte
<script lang="ts">
	import { Button, Field } from '$lib/design-system';
	let name = $state('');
	let control = $state<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null>(null);
</script>

<Field label="Nombre" bind:value={name} bind:control required />
<Button onclick={() => control?.focus()}>Editar nombre</Button>
<Button href="/profile">Mi perfil</Button>
```

## Application adapters and specialized controls

`components/TopBar` preserves cold-load back destinations and modifier-click behavior. `components/Toast` maps the existing `showToast` API to `Toast`; ID-guarded dismissal prevents an old message from clearing a replacement. `components/ConfirmDialog` preserves existing conditional-mount callers.

Official levels use labeled native radio inputs in `LevelSelector`; evidence ratings use the distinct underlined `LevelScale`. Null remains unset. `LevelBadge` is plain readable text. `ScoreRuler` retains pointer preview with commit on release and keyboard increments. No UI component computes an official level from evidence or internal grades.

`RecordingControl` preserves immediate microphone capture, a 400ms commitment threshold, pointer/keyboard holds, and the 60-second cap. It uses a solid Índigo control and linear progress. Short taps discard; microphone failures reset the UI; unmount cancels capture and releases microphone tracks. The voice player uses shared controls and reports playback failures.

## Verification

Run from `mawta-ui`:

```sh
bun install --frozen-lockfile
bunx playwright install chromium webkit
bun run check
bun eslint .
bun run test:components
bun run test:ui
bun run build
```

Component tests run in Chromium and WebKit. Route tests start isolated local Vite servers, intercept API requests, and cover all 17 screens plus the error page. They exercise planning with its flag both enabled and disabled, authentication, navigation, assessment contracts, recording, and undo. Screen tests capture 320px, 390px, 480px, and desktop screenshots under ignored `test-results/` artifacts.

Media tests use deterministic microphone and audio stubs. They verify interaction and lifecycle contracts; they do not establish physical microphone quality or live backend availability. No production credentials or database are needed.
