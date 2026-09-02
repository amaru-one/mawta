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

	const dateLabel = $derived.by(() => {
		const d = $currentSession?.date;
		if (!d) return '';
		const day = d.getDate();
		const month = d.toLocaleDateString('es-PE', { month: 'short' }).replace('.', '').toUpperCase();
		return `${day} ${month}`;
	});

	const metaLine = $derived(
		[($currentCourse?.name ?? '').toUpperCase(), dateLabel].filter(Boolean).join(' · ')
	);

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
	<TopBar back="/class/{courseId}" recording={phase === 'recording'} />

	<div class="stage">
		<div class="head" class:receded={stage === 'recording'}>
			<p class="metaline">{metaLine}</p>

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
							onpointerdown={(e) => {
								e.preventDefault();
								pick(s);
							}}
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
	}

	.head {
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		padding: 18px 18px 0;
		z-index: 3;
		transition: opacity 220ms ease-out;
	}

	.head.receded {
		opacity: 0.45;
	}

	.metaline {
		margin: 0 0 14px;
		font-family: var(--font-mono);
		font-size: 11px;
		letter-spacing: 0.08em;
		color: var(--text-muted);
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
		font-size: 26px;
		font-weight: 600;
		letter-spacing: -0.02em;
		line-height: 1.15;
		color: var(--text-primary);
	}

	.namefield::placeholder {
		color: var(--text-muted);
		font-weight: 600;
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
		font-size: 26px;
		font-weight: 600;
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
		box-shadow: 0 12px 34px rgba(20, 20, 20, 0.14);
		overflow-y: auto;
		max-height: 46vh;
		-webkit-overflow-scrolling: touch;
	}

	.rrow {
		display: flex;
		align-items: center;
		gap: 12px;
		width: 100%;
		padding: 13px 14px;
		text-align: left;
		border-bottom: 0.5px solid var(--border);
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

	/* Both pinned off the stage centre, never off the bubble, so neither moves
	   when the bubble changes character. */
	.hint {
		position: absolute;
		top: 50%;
		left: 0;
		right: 0;
		margin: 0;
		transform: translateY(122px);
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
		top: 50%;
		left: 0;
		right: 0;
		margin: 0;
		transform: translateY(152px);
		text-align: center;
		font-size: 13px;
		color: var(--text-secondary);
		font-variant-numeric: tabular-nums;
		z-index: 3;
	}

	.notes {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
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

	/* On a short viewport the bottom-pinned notes would collide with the
	   countdown. Drop the notes rather than shrink the bubble — the bubble
	   holding its size is the point of the screen. */
	@media (max-height: 640px) {
		.notes {
			display: none;
		}
	}
</style>
