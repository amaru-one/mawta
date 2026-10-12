<script lang="ts">
	import { IconButton } from '$lib/design-system';
	import { onDestroy } from 'svelte';

	import { showToast } from '$lib/toast';
	import { noteAudio } from '$lib/lesson';
	import { audioContext, decodeBlob, formatDuration } from '$lib/recorder';
	import type { Note } from '$lib/types';
	import ConfirmDialog from './ConfirmDialog.svelte';

	interface Props {
		note: Note;
		// Without it the note is read-only: no delete button (e.g. a note shown
		// for review, which the teacher moves or confirms instead).
		ondelete?: (note: Note) => void;
	}

	let { note, ondelete }: Props = $props();

	let alive = true;
	let loading = $state(false);
	let playing = $state(false);
	let position = $state(0);
	let measuredDuration = $state(0);
	let showDeleteConfirm = $state(false);

	const duration = $derived(measuredDuration || note.durationMs / 1000);

	let buffer: AudioBuffer | null = null;
	let source: AudioBufferSourceNode | null = null;
	let startedAt = 0;
	let pausedOffset = 0;
	let stopping = false;
	let posTimer: ReturnType<typeof setInterval> | undefined;

	function pause(): void {
		if (!source) return;
		stopping = true;
		pausedOffset = position;
		source.stop();
		source = null;
		playing = false;
		clearInterval(posTimer);
	}

	async function play(): Promise<void> {
		if (playing) {
			pause();
			return;
		}
		const ctx = audioContext();
		if (!buffer) {
			const blob = await noteAudio(note);
			if (!blob) throw new Error('audio unavailable');
			buffer = await decodeBlob(blob);
		}
		if (!buffer) throw new Error('audio unavailable');
		if (!alive) return;
		if (!measuredDuration) measuredDuration = buffer.duration;

		stopping = false;
		source = ctx.createBufferSource();
		source.buffer = buffer;
		source.connect(ctx.destination);
		source.onended = () => {
			if (stopping) return;
			playing = false;
			position = 0;
			pausedOffset = 0;
			source = null;
			clearInterval(posTimer);
		};
		startedAt = ctx.currentTime;
		source.start(0, pausedOffset);
		playing = true;
		posTimer = setInterval(() => {
			position = pausedOffset + (ctx.currentTime - startedAt);
		}, 100);
	}

	async function togglePlay(): Promise<void> {
		if (loading) return;
		loading = true;
		try {
			await play();
		} catch {
			if (alive) showToast('No se pudo reproducir la nota. Intenta de nuevo.');
		} finally {
			if (alive) loading = false;
		}
	}

	onDestroy(() => {
		alive = false;
		clearInterval(posTimer);
		if (source) {
			stopping = true;
			source.stop();
		}
	});
</script>

<div class="note row" role="group" aria-label="Nota de voz">
	<IconButton
		icon={playing ? 'pause' : 'play'}
		label={playing ? 'Pausar nota' : 'Reproducir nota'}
		onclick={togglePlay}
		disabled={loading}
	/>

	<button
		class="meta pressable"
		onclick={togglePlay}
		aria-label={playing ? 'Pausar nota' : 'Reproducir nota'}
		disabled={loading}
	>
		<span class="duration">
			{playing ? formatDuration(position) : formatDuration(duration)}
		</span>
		{#if note.transcript}
			<span class="transcript">“{note.transcript}”</span>
		{/if}
	</button>

	{#if ondelete}
		<IconButton icon="trash" label="Eliminar nota" onclick={() => (showDeleteConfirm = true)} />
	{/if}
</div>

{#if showDeleteConfirm && ondelete}
	<ConfirmDialog
		title="¿Eliminar esta nota?"
		description="Esta acción no se puede deshacer."
		confirmLabel="Eliminar"
		onconfirm={() => {
			ondelete(note);
			showDeleteConfirm = false;
		}}
		oncancel={() => (showDeleteConfirm = false)}
	/>
{/if}

<style>
	.note {
		gap: var(--mw-space-2);
		padding: var(--mw-space-3);
		border: 1px solid var(--mw-line);
		border-radius: var(--mw-radius-xl);
		background: var(--mw-surface-card);
	}
	.meta {
		display: grid;
		gap: var(--mw-space-1);
		flex: 1;
		min-width: 0;
		text-align: left;
		min-height: var(--mw-touch-target);
	}
	.duration {
		font-size: var(--mw-type-small-size);
		color: var(--mw-ink);
		font-variant-numeric: tabular-nums;
	}
	.transcript {
		font-size: var(--mw-type-caption-size);
		color: var(--mw-ink-muted);
	}
</style>
