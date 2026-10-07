<script lang="ts">
	import { Button, Field, Icon, IconButton, LoadingState } from '$lib/design-system';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import RecordingControl, { type RecordPhase } from '$lib/components/RecordingControl.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import VoiceNotePlayer from '$lib/components/VoiceNotePlayer.svelte';
	import { hapticTap } from '$lib/haptics';
	import { addNote, loadSession, removeNote } from '$lib/lesson';
	import { MAX_RECORD_SEC, formatDuration } from '$lib/recorder';
	import { currentCourse, currentSession, entryKey, notes, students } from '$lib/stores';
	import { showToast } from '$lib/toast';
	import type { Note, Student } from '$lib/types';

	const courseId = $derived(page.params.courseId ?? '');
	const sessionId = $derived(page.params.sessionId ?? '');
	// Home marks its links `?from=home`; the área marks its own `?from=area`. The
	// origin decides this screen's parent: Home, or the área. From Home the área
	// is a forward step (the "Ir a {área}" button below), never a way back.
	const fromHome = $derived(page.url.searchParams.get('from') === 'home');

	let ready = $state(false);
	let loadError = $state(false);
	let query = $state('');
	let searching = $state(false);
	let selectedId = $state<string | null>(null);
	let phase = $state<RecordPhase>('idle');
	let elapsedSec = $state(0);
	let field = $state<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null>(null);

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

	// The selected student has notes to show right now. Drives both the panel
	// below and — on a short viewport — whether the stage becomes scrollable so
	// the list is reachable at all (see the `@media (max-height: 800px)` block).
	const showNotes = $derived(!!selected && stage !== 'recording' && selectedNotes.length > 0);

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
				// Pointer already gone — capture is best-effort, as in RecordingControl.
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

	// Two meanings, chosen by whether a student is already picked. With a
	// selection: start over — clear it and re-open the picker, since with no
	// roster on screen the panel is the only way to reach a student. Without
	// one: the panel is already open and this really is a close button, so it
	// closes the panel instead of re-opening it (a no-op the button's own
	// "x" promised but never did). Either way it is reachable again — the
	// field's own `onfocus` re-opens the panel — so closing loses nothing.
	function clearAll(): void {
		hapticTap();
		query = '';
		if (selected) {
			selectedId = null;
			searching = true;
			field?.focus();
		} else {
			searching = false;
			field?.blur();
		}
	}

	function handleRecorded(blob: Blob, durationSec: number): void {
		if (!selectedId) return;
		void addNote(selectedId, blob, durationSec);
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
<div class="view">
	<div class="screen" class:withnotes={showNotes}>
		<TopBar back={fromHome ? '/' : `/class/${courseId}`} recording={phase === 'recording'} />

		<div class="stage">
			{#if !ready && !loadError}<LoadingState label="Cargando sesión…" />{/if}
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
						<span class="lessonname">{lessonName}</span>
					</div>
				</div>

				<div class="nameline" class:live={stage === 'recording'}>
					<Field
						label="Buscar alumno"
						type="search"
						bind:control={field}
						bind:value={query}
						placeholder={selected ? fullName(selected) : 'Nombre o apellido'}
						onfocus={() => (searching = true)}
						enterkeyhint="search"
						autocomplete="off"
						autocapitalize="off"
						spellcheck={false}
						disabled={phase !== 'idle'}
					/>
					{#if selected && !searching}<p class="selected-name">{fullName(selected)}</p>{/if}
					{#if stage !== 'recording'}
						<IconButton
							icon="x"
							label={selected ? 'Borrar y elegir otro alumno' : 'Cerrar lista de alumnos'}
							onclick={clearAll}
						/>
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

				<!-- Only offered when the lesson was opened from Home: that is the way
			     down to the área. From the área, "Volver" already leads there. Last in
			     the header, so hiding it moves nothing above it. -->
				{#if stage !== 'recording' && !panelOpen && fromHome}
					<a class="area pressable" href="/class/{courseId}" onclick={hapticTap}>
						<span class="areatxt">Ir a {areaName}</span>
						<Icon name="chevron-right" size={19} />
					</a>
				{/if}
			</div>

			<RecordingControl
				armed={!!selected && !searching}
				bind:phase
				bind:elapsedSec
				onrecorded={handleRecorded}
			/>

			<p class="hint" class:quiet={stage === 'searching'} aria-live="polite">{hint}</p>

			{#if stage === 'recording'}
				<p class="count" aria-hidden="true">quedan {remainingSec} s</p>
			{/if}

			{#if showNotes}
				<div class="notes">
					<p class="eyebrow">Notas de hoy</p>
					<div class="notelist">
						{#each selectedNotes as note (note.id)}
							<VoiceNotePlayer {note} ondelete={handleDelete} />
						{/each}
					</div>
				</div>
			{/if}

			{#if loadError}
				<p class="loaderr">
					No se pudo cargar la sesión.
					<Button variant="secondary" onclick={load}>Reintentar</Button>
				</p>
			{/if}
		</div>
	</div>
</div>

<style>
	.screen {
		min-height: 100dvh;
		background: var(--mw-surface-card);
	}
	.stage {
		padding: var(--mw-space-5);
	}
	.metacard {
		padding: var(--mw-space-4);
		border-radius: var(--mw-radius-xl);
		background: var(--mw-surface-tint);
		margin-bottom: var(--mw-space-5);
	}
	.metatop {
		display: flex;
		gap: var(--mw-space-3);
		align-items: center;
	}
	.cal {
		color: var(--mw-accent);
	}
	.metatext {
		display: grid;
		gap: var(--mw-space-1);
		min-width: 0;
	}
	.areaname {
		font-size: var(--mw-type-heading-size);
		font-weight: 700;
	}
	.dateline,
	.subline {
		font-size: var(--mw-type-caption-size);
		color: var(--mw-ink-muted);
	}
	.hair {
		height: 1px;
		background: var(--mw-line);
		margin: var(--mw-space-3) 0;
	}
	.lessonname {
		font-weight: 600;
	}
	.nameline {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 40px;
		align-items: end;
		gap: var(--mw-space-2);
	}
	.selected-name {
		grid-column: 1;
		margin: 0;
		font-size: var(--mw-type-heading-size);
		font-weight: 700;
	}
	.nameline :global(.mw-icon-button) {
		grid-column: 2;
		grid-row: 1;
		margin-bottom: 4px;
	}
	.subline {
		margin: var(--mw-space-2) 0;
	}
	.results {
		max-height: 280px;
		overflow-y: auto;
		border: 1px solid var(--mw-line);
		border-radius: var(--mw-radius-xl);
	}
	.rrow {
		display: flex;
		align-items: center;
		gap: var(--mw-space-3);
		width: 100%;
		padding: var(--mw-space-3);
		min-height: 56px;
		text-align: left;
		border-bottom: 1px solid var(--mw-line);
	}
	.rrow[aria-selected='true'] {
		background: var(--mw-surface-tint);
	}
	.rav {
		width: 40px;
		height: 40px;
		border-radius: 50%;
		background: var(--mw-surface-page);
		display: grid;
		place-items: center;
		color: var(--mw-ink-secondary);
		font-size: var(--mw-type-small-size);
		flex-shrink: 0;
	}
	.rname {
		flex: 1;
		min-width: 0;
	}
	mark {
		background: var(--mw-surface-tint);
		color: var(--mw-accent);
	}
	.rnotes {
		font-size: var(--mw-type-caption-size);
		color: var(--mw-ink-muted);
	}
	.rempty {
		padding: var(--mw-space-4);
	}
	.area {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--mw-space-2);
		min-height: 48px;
		color: var(--mw-accent);
		font-weight: 600;
	}
	.hint,
	.count {
		margin: var(--mw-space-2) 0;
		text-align: center;
		font-size: var(--mw-type-small-size);
		color: var(--mw-ink-secondary);
	}
	.notes {
		margin-top: var(--mw-space-6);
	}
	.notelist {
		display: grid;
		gap: var(--mw-space-3);
	}
	.loaderr {
		color: var(--mw-danger);
	}
</style>
