<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import Icon from '$lib/components/Icon.svelte';
	import RecordBubble, { type RecordPhase } from '$lib/components/RecordBubble.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import VoiceNotePlayer from '$lib/components/VoiceNotePlayer.svelte';
	import { hapticTap } from '$lib/haptics';
	import { addNote, loadSession, removeNote, saveNote } from '$lib/lesson';
	import { MAX_RECORD_SEC, formatDuration } from '$lib/recorder';
	import { currentCourse, currentSession, entryKey, notes, students } from '$lib/stores';
	import { showToast } from '$lib/toast';
	import type { Note, Student } from '$lib/types';

	const courseId = $derived(page.params.courseId ?? '');
	const sessionId = $derived(page.params.sessionId ?? '');
	// The área's hero/rails mark their own links so this screen knows a forward
	// path back to área already sits one step behind in history — see the
	// "Ir a {área}" button below.
	const cameFromArea = $derived(page.url.searchParams.get('from') === 'area');

	let ready = $state(false);
	let loadError = $state(false);
	let query = $state('');
	let searching = $state(false);
	let selectedId = $state<string | null>(null);
	let phase = $state<RecordPhase>('idle');
	let elapsedSec = $state(0);
	let field = $state<HTMLInputElement | null>(null);

	const fullName = (s: Student): string => `${s.firstName} ${s.lastName}`;
	const initials = (s: Student): string =>
		`${s.firstName.charAt(0)}${s.lastName.charAt(0)}`.toUpperCase();

	const selected = $derived($students.find((s) => s.id === selectedId) ?? null);

	// Filtered client-side over the roster already in the store. `getSession`
	// takes a `q` parameter, but a loaded roster answers instantly and the
	// server round-trip would only add latency between keystrokes.
	const matches = $derived.by(() => {
		const q = query.trim().toLowerCase();
		if (q === '') return $students;
		return $students.filter((s) => fullName(s).toLowerCase().includes(q));
	});

	const selectedNotes = $derived.by(() => {
		const sid = $currentSession?.id;
		if (!sid || !selectedId) return [];
		return $notes.get(entryKey(sid, selectedId)) ?? [];
	});

	const notesTotalSec = $derived(selectedNotes.reduce((sum, n) => sum + n.durationMs, 0) / 1000);

	// One derived screen state. 'pressing' still reads as armed — the bubble
	// only changes character once the hold commits.
	const stage = $derived<'searching' | 'armed' | 'recording'>(
		phase === 'recording' ? 'recording' : selected && !searching ? 'armed' : 'searching'
	);

	const panelOpen = $derived(ready && searching && stage !== 'recording');

	const areaName = $derived($currentCourse?.name ?? 'Clase');

	// "Viernes 4 de setiembre", built from two calls rather than one
	// weekday+day+month format: that format's separator is an ICU detail that
	// varies by version, and this line is read at a glance every session.
	const dateLine = $derived.by(() => {
		const d = $currentSession?.date;
		if (!d) return '';
		const weekday = d.toLocaleDateString('es-PE', { weekday: 'long' });
		const rest = d.toLocaleDateString('es-PE', { day: 'numeric', month: 'long' });
		return `${weekday.charAt(0).toUpperCase()}${weekday.slice(1)} ${rest}`;
	});

	// The class dashboard's wording for a session with no topic, deliberately
	// the same string: it is the same absence.
	const lessonName = $derived($currentSession?.topic?.trim() || 'Sin tema asignado');

	const subLine = $derived.by(() => {
		if (stage === 'searching') {
			const n = matches.length;
			if (n === 0) return 'SIN COINCIDENCIAS';
			return n === 1 ? '1 COINCIDENCIA' : `${n} COINCIDENCIAS`;
		}
		if (!selected) return '';
		const n = selectedNotes.length;
		const label = n === 1 ? '1 NOTA HOY' : `${n} NOTAS HOY`;
		return n === 0 ? label : `${label} · ${formatDuration(notesTotalSec)}`;
	});

	const remainingSec = $derived(Math.max(0, Math.ceil(MAX_RECORD_SEC - elapsedSec)));

	const hint = $derived(
		stage === 'recording'
			? 'Suelta para guardar'
			: stage === 'armed'
				? 'Mantén para grabar'
				: 'Elige un nombre para grabar'
	);

	const noteCountFor = (s: Student): number => {
		const sid = $currentSession?.id;
		if (!sid) return 0;
		return ($notes.get(entryKey(sid, s.id)) ?? []).length;
	};

	// Splits a name around the matched run so it can be highlighted in place.
	const splitMatch = (name: string, q: string): [string, string, string] => {
		const needle = q.trim().toLowerCase();
		if (needle === '') return [name, '', ''];
		const at = name.toLowerCase().indexOf(needle);
		if (at === -1) return [name, '', ''];
		return [name.slice(0, at), name.slice(at, at + needle.length), name.slice(at + needle.length)];
	};

	function pick(student: Student): void {
		hapticTap();
		selectedId = student.id;
		query = '';
		searching = false;
		field?.blur();
	}

	// A tap picks a name; a drag scrolls the list. Which of the two a touch is
	// cannot be known at `pointerdown` — the finger has not moved yet — so the
	// row commits on RELEASE, having held the student since the press. Same
	// shape as `ScoreRuler`'s pointer-captured drag, except a `pointercancel`
	// here ABORTS: a cancel means the browser took the gesture to scroll.
	const TAP_SLOP = 10;

	let pending: { id: number; x: number; y: number; student: Student } | null = null;

	const travelled = (e: PointerEvent, from: { x: number; y: number }): number =>
		Math.hypot(e.clientX - from.x, e.clientY - from.y);

	function rowDown(event: PointerEvent, student: Student): void {
		// Captured so the release lands on this row even if the layout shifts
		// under the finger (the software keyboard closing is the usual cause).
		if (event.currentTarget instanceof HTMLElement) {
			try {
				event.currentTarget.setPointerCapture(event.pointerId);
			} catch {
				// Pointer already gone — capture is best-effort, as in RecordBubble.
			}
		}
		pending = { id: event.pointerId, x: event.clientX, y: event.clientY, student };
	}

	function rowMove(event: PointerEvent): void {
		if (pending === null || event.pointerId !== pending.id) return;
		if (travelled(event, pending) > TAP_SLOP) pending = null;
	}

	function rowUp(event: PointerEvent): void {
		const held = pending;
		pending = null;
		if (held === null || event.pointerId !== held.id) return;
		if (travelled(event, held) > TAP_SLOP) return;
		// Suppress the compatibility click: the panel closes with this commit,
		// and that click would land on whatever is now under the finger.
		event.preventDefault();
		pick(held.student);
	}

	// The browser claimed the gesture — it is a scroll, not a choice.
	function rowCancel(): void {
		pending = null;
	}

	// Keyboard and assistive tech only: those clicks carry no pointer detail,
	// and every pointer-driven click is prevented in `rowUp`.
	function rowClick(event: MouseEvent, student: Student): void {
		if (event.detail === 0) pick(student);
	}

	// One meaning: start over. Clears the query AND the selection and re-opens
	// the picker — with no roster on screen this panel is the only way to reach
	// a student, so the clear button has to be able to get back to it.
	function clearAll(): void {
		hapticTap();
		query = '';
		selectedId = null;
		searching = true;
		field?.focus();
	}

	function handleRecorded(blob: Blob, durationSec: number): void {
		if (!selectedId) return;
		void addNote(selectedId, blob, durationSec);
		showToast('Nota guardada');
	}

	function handleSave(note: Note): void {
		hapticTap();
		saveNote(note);
		showToast('Nota guardada');
	}

	function handleDelete(note: Note): void {
		removeNote(note);
		showToast('Nota eliminada');
	}

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			await loadSession(sessionId);
			ready = true;
		} catch {
			loadError = true;
		}
	}

	onMount(load);
</script>

<svelte:head>
	<title>{$currentCourse?.name ?? 'Clase'} — Lección</title>
</svelte:head>

<div class="screen">
	<!-- Reached from Home as often as from the área now, so a fixed back
	     destination would send the teacher to a screen they never saw. -->
	<TopBar back="/class/{courseId}" useHistory recording={phase === 'recording'} />

	<div class="stage">
		<div class="head" class:receded={stage === 'recording'}>
			<!-- The session's identity, in one card: which área, which day, which
			     lesson. All three are constant for the whole session, so the card
			     never changes height between the three stage states. -->
			<div class="metacard">
				<div class="metatop">
					<span class="cal"><Icon name="calendar" size={19} /></span>
					<span class="metatext">
						<span class="areaname">{areaName}</span>
						<span class="dateline">{dateLine}</span>
					</span>
				</div>

				<div class="hair"></div>

				<div class="lesson">
					<span class="lessonlbl">Lección de hoy</span>
					<span class="lessonname">{lessonName}</span>
				</div>
			</div>

			<div class="nameline" class:live={stage === 'recording'}>
				<input
					class="namefield"
					bind:this={field}
					bind:value={query}
					placeholder={selected ? '' : 'Buscar alumno'}
					onfocus={() => (searching = true)}
					enterkeyhint="search"
					autocomplete="off"
					autocapitalize="off"
					spellcheck="false"
					aria-label="Buscar alumno"
					disabled={stage === 'recording'}
				/>
				{#if selected && !searching && query === ''}
					<span class="namefill" aria-hidden="true">{fullName(selected)}</span>
				{/if}
				{#if stage !== 'recording'}
					<button class="clear" onclick={clearAll} aria-label="Borrar y elegir otro alumno">
						<Icon name="x" size={13} />
					</button>
				{/if}
			</div>

			<p class="subline">{subLine}</p>

			{#if panelOpen}
				<div class="results" role="listbox" aria-label="Alumnos">
					{#each matches as s (s.id)}
						{@const parts = splitMatch(fullName(s), query)}
						{@const count = noteCountFor(s)}
						<button
							class="rrow"
							role="option"
							aria-selected={s.id === selectedId}
							onpointerdown={(e) => rowDown(e, s)}
							onpointermove={rowMove}
							onpointerup={rowUp}
							onpointercancel={rowCancel}
							onclick={(e) => rowClick(e, s)}
						>
							<span class="rav">{initials(s)}</span>
							<span class="rname">
								{parts[0]}{#if parts[1]}<mark>{parts[1]}</mark>{/if}{parts[2]}
							</span>
							{#if count > 0}
								<span class="rnotes">{count === 1 ? '1 nota' : `${count} notas`}</span>
							{/if}
						</button>
					{/each}
					{#if matches.length === 0}
						<p class="rempty">Ningún alumno coincide con «{query}».</p>
					{/if}
				</div>
			{/if}

			<!-- The only navigation on the stage — except when área is already one
			     step behind in history (cameFromArea): then the back arrow is the
			     sole way out, on purpose, so área↔burbuja can't push an ever-longer
			     history chain. Last in the header, so hiding it moves nothing above
			     it. -->
			{#if stage !== 'recording' && !panelOpen && !cameFromArea}
				<a class="area pressable" href="/class/{courseId}" onclick={hapticTap}>
					<span class="areatxt">Ir a {areaName}</span>
					<Icon name="chevron-right" size={19} />
				</a>
			{/if}
		</div>

		<RecordBubble armed={!!selected} bind:phase bind:elapsedSec onrecorded={handleRecorded} />

		<p class="hint" class:quiet={stage === 'searching'} aria-live="polite">{hint}</p>

		{#if stage === 'recording'}
			<p class="count" aria-hidden="true">quedan {remainingSec} s</p>
		{/if}

		{#if selected && stage !== 'recording' && selectedNotes.length > 0}
			<div class="notes">
				<p class="eyebrow">Notas de hoy</p>
				<div class="notelist">
					{#each selectedNotes as note (note.id)}
						<VoiceNotePlayer {note} ondelete={handleDelete} onsave={handleSave} />
					{/each}
				</div>
			</div>
		{/if}

		{#if loadError}
			<p class="loaderr">
				No se pudo cargar la sesión.
				<button class="pill-light pressable" onclick={load}>Reintentar</button>
			</p>
		{/if}
	</div>
</div>

<style>
	/* A fixed stage: one viewport, no scroll, nothing reflows between the three
	   states. This route deliberately does not use the global `.body` gutter —
	   it has no document flow to gutter. */
	.screen {
		height: 100dvh;
		display: flex;
		flex-direction: column;
		overflow: hidden;
		background: var(--surface-2);
		overscroll-behavior: none;
	}

	.stage {
		position: relative;
		flex: 1;
		min-height: 0;

		/* The composition's anchors, in one place. The bubble, the hint, the
		   countdown and the notes panel all hang off --bubble-anchor, so they
		   move as one piece and cannot drift out of register. They never vary by
		   state — only by viewport, below.

		   The anchor is a fixed distance from the top, not a percentage of the
		   stage: the header above it is a constant 324px tall, so px anchoring
		   keeps the same gap under it on every screen and hands the slack on a
		   tall screen to the notes panel, which is the only part that can use
		   it. A percentage put the orb under the header on short screens and
		   left a hole on tall ones. */
		--bubble-anchor: 460px;
		--bubble-scale: 1;
		--hint-offset: 128px;
		--count-offset: 158px;
		--notes-offset: 172px;
	}

	/* Above the hint, not level with it: the results panel is part of this
	   header, and at the same z-index the pinned hint printed through the list
	   of names the panel is busy answering. */
	.head {
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		padding: 18px 18px 0;
		z-index: 4;
		transition: opacity 220ms ease-out;
	}

	.head.receded {
		opacity: 0.45;
	}

	.metacard {
		background: var(--aurora-tint);
		border-radius: 16px;
		padding: 12px 14px;
		margin-bottom: 16px;
	}

	.metatop {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.cal {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 38px;
		height: 38px;
		border-radius: 11px;
		flex-shrink: 0;
		background: linear-gradient(135deg, var(--aurora-1), var(--aurora-2));
		color: var(--on-accent);
	}

	.metatext {
		display: flex;
		flex-direction: column;
		gap: 1px;
		min-width: 0;
	}

	.areaname {
		font-size: 16px;
		font-weight: 800;
		letter-spacing: -0.01em;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.dateline {
		font-size: 13px;
		font-weight: 600;
		color: var(--aurora-deep);
	}

	.hair {
		height: 1px;
		background: rgba(74, 95, 214, 0.14);
		margin: 11px 0 10px;
	}

	.lesson {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.lessonlbl {
		font-family: var(--font-mono);
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	.lessonname {
		font-size: 16px;
		font-weight: 700;
		letter-spacing: -0.01em;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	/* The way back up to the área, and the only navigation on the stage. It
	   carries the bubble's own palette rather than a neutral pill: it is the one
	   thing on the screen that is not the recording, and it has to be findable
	   without hunting. */
	.area {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 10px;
		margin-top: 18px;
		padding: 19px 22px;
		border-radius: 999px;
		background: linear-gradient(120deg, var(--aurora-deep), var(--aurora-1));
		color: var(--on-accent);
		font-size: 17px;
		font-weight: 700;
		box-shadow: 0 12px 26px rgba(74, 95, 214, 0.32);
	}

	.areatxt {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.nameline {
		position: relative;
		display: flex;
		align-items: center;
		gap: 10px;
		padding-bottom: 12px;
		border-bottom: 1px solid var(--text-primary);
	}

	.nameline.live {
		border-bottom-color: var(--border);
	}

	/* The name line IS the field — no box, no pill, no leading icon. */
	.namefield {
		flex: 1;
		min-width: 0;
		border: none;
		background: none;
		padding: 0;
		outline: none;
		font-size: 34px;
		font-weight: 700;
		letter-spacing: -0.02em;
		line-height: 1.15;
		color: var(--text-primary);
	}

	.namefield::placeholder {
		color: var(--text-muted);
		font-weight: 700;
	}

	.namefield:disabled {
		color: var(--text-primary);
		opacity: 1;
		-webkit-text-fill-color: currentColor;
	}

	/* The chosen name is painted over the empty field, so "typing replaces the
	   name" stays true without a did-they-edit-it state machine. */
	.namefill {
		position: absolute;
		left: 0;
		right: 36px;
		font-size: 34px;
		font-weight: 700;
		letter-spacing: -0.02em;
		line-height: 1.15;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		pointer-events: none;
	}

	.clear {
		position: relative;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 26px;
		height: 26px;
		border-radius: 50%;
		background: var(--surface-1);
		color: var(--text-secondary);
		flex-shrink: 0;
	}

	/* 44px minimum tap target via an invisible halo. */
	.clear::after {
		content: '';
		position: absolute;
		inset: -9px;
	}

	.subline {
		margin: 8px 0 0;
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--text-muted);
		/* Holds its height when empty so the panel below never jumps. */
		min-height: 17px;
	}

	/* Results hang off the underline — not centred — and float over the bubble. */
	.results {
		margin-top: 8px;
		background: var(--surface-2);
		border: 0.5px solid var(--border);
		border-radius: 14px;
		box-shadow: 0 12px 34px rgba(35, 40, 90, 0.14);
		overflow-y: auto;
		max-height: 46vh;
		-webkit-overflow-scrolling: touch;
		/* The bounce at either end stays in the panel rather than chaining out
		   to the stage behind it. */
		overscroll-behavior: contain;
	}

	/* `pan-y` states what the row does NOT handle, so the browser can start
	   scrolling the panel on the first move instead of waiting on script; the
	   selection idioms live in the pointer handlers. The callout/selection
	   suppression stops a slow drag over a name from raising iOS's text-
	   selection menu on top of the list. */
	.rrow {
		display: flex;
		align-items: center;
		gap: 12px;
		width: 100%;
		padding: 13px 14px;
		text-align: left;
		border-bottom: 0.5px solid var(--border);
		touch-action: pan-y;
		user-select: none;
		-webkit-user-select: none;
		-webkit-touch-callout: none;
	}

	.rrow:last-child {
		border-bottom: none;
	}

	.rav {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		background: var(--surface-1);
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 11px;
		font-weight: 500;
		flex-shrink: 0;
	}

	.rname {
		flex: 1;
		min-width: 0;
		font-size: 17px;
		font-weight: 500;
	}

	.rname mark {
		background: var(--bg-accent);
		color: var(--text-accent);
	}

	.rnotes {
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--text-muted);
		flex-shrink: 0;
	}

	.rempty {
		margin: 0;
		padding: 16px 14px;
		font-size: 14px;
		color: var(--text-secondary);
	}

	/* Both pinned off the stage's anchor, never off the bubble, so neither moves
	   when the bubble changes character. */
	.hint {
		position: absolute;
		top: var(--bubble-anchor);
		left: 0;
		right: 0;
		margin: 0;
		transform: translateY(var(--hint-offset));
		text-align: center;
		font-size: 15px;
		font-weight: 500;
		color: var(--text-primary);
		z-index: 3;
	}

	.hint.quiet {
		font-weight: 400;
		color: var(--text-muted);
	}

	.count {
		position: absolute;
		top: var(--bubble-anchor);
		left: 0;
		right: 0;
		margin: 0;
		transform: translateY(var(--count-offset));
		text-align: center;
		font-size: 13px;
		color: var(--text-secondary);
		font-variant-numeric: tabular-nums;
		z-index: 3;
	}

	/* Bounded above by the anchor, not by its own content: the list scrolls
	   inside whatever the composition leaves it, so a student with six notes
	   grows a scrollbar instead of growing up over the bubble. */
	.notes {
		position: absolute;
		left: 0;
		right: 0;
		top: calc(var(--bubble-anchor) + var(--notes-offset));
		bottom: 0;
		display: flex;
		flex-direction: column;
		min-height: 0;
		padding: 0 18px 24px;
		z-index: 3;
		background: var(--surface-2);
	}

	.notes .eyebrow {
		margin: 0 0 10px;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	.notelist {
		display: flex;
		flex-direction: column;
		gap: 6px;
		min-height: 0;
		overflow-y: auto;
		-webkit-overflow-scrolling: touch;
	}

	.loaderr {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		margin: 0;
		padding: 0 18px 24px;
		font-size: 14px;
		color: var(--text-secondary);
		z-index: 4;
		background: var(--surface-2);
	}

	/* A short viewport cannot hold the context card, the orb and the notes at
	   once. The notes go first, as they always have — reading them is a
	   different job, and the orb holding its size is the point of the screen.
	   The breakpoint moved up from 640px when the header gained the
	   área/fecha/lección card: below ~800px what was left for the panel was
	   less than one row. */
	@media (max-height: 800px) {
		.notes {
			display: none;
		}
	}

	/* Shorter still, and the orb does give ground rather than run off the
	   bottom: it shrinks in place and pulls the two pinned lines up with it. */
	@media (max-height: 700px) {
		.stage {
			--bubble-anchor: 430px;
			--bubble-scale: 0.74;
			--hint-offset: 100px;
			--count-offset: 126px;
		}
	}
</style>
