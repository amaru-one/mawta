<script lang="ts">
	import { onDestroy } from 'svelte';
	import { fly } from 'svelte/transition';
	import { noteAudio } from '$lib/lesson';
	import { audioContext, decodeBlob, formatDuration } from '$lib/recorder';
	import type { Note } from '$lib/types';
	import ConfirmDialog from './ConfirmDialog.svelte';
	import Icon from './Icon.svelte';

	interface Props {
		note: Note;
		ondelete: (note: Note) => void;
		onsave: (note: Note) => void;
	}

	let { note, ondelete, onsave }: Props = $props();

	let playing = $state(false);
	let position = $state(0);
	let measuredDuration = $state(0);
	let showDeleteConfirm = $state(false);

	// The store swaps in the updated note after a save, so this flows down.
	const isSaved = $derived(note.status === 'saved');

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

	async function togglePlay(): Promise<void> {
		if (playing) {
			pause();
			return;
		}
		const ctx = audioContext();
		if (!buffer) {
			const blob = await noteAudio(note);
			if (!blob) return;
			buffer = await decodeBlob(blob);
		}
		if (!buffer) return;
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

	onDestroy(() => {
		clearInterval(posTimer);
		if (source) {
			stopping = true;
			source.stop();
		}
	});
</script>

<div
	class="note row"
	in:fly={{ x: -20, duration: 150 }}
	out:fly={{ x: 100, duration: 200 }}
	role="group"
	aria-label="Nota de voz"
>
	<button
		class="play pressable"
		onclick={togglePlay}
		aria-label={playing ? 'Pausar nota' : 'Reproducir nota'}
	>
		<Icon name={playing ? 'pause' : 'play'} size={14} />
	</button>

	<button class="meta pressable" onclick={togglePlay} aria-label="Reproducir nota">
		<span class="duration">
			{playing ? formatDuration(position) : formatDuration(duration)}
		</span>
		{#if note.transcript}
			<span class="transcript">“{note.transcript}”</span>
		{/if}
	</button>

	<button
		class="action pressable"
		class:saved={isSaved}
		onclick={() => onsave(note)}
		aria-label="Guardar nota"
		title="Guardar nota"
	>
		<Icon name="save" size={15} />
	</button>
	<button
		class="action delete pressable"
		onclick={() => (showDeleteConfirm = true)}
		aria-label="Eliminar nota"
		title="Eliminar nota"
	>
		<Icon name="trash" size={15} />
	</button>
</div>

{#if showDeleteConfirm}
	<ConfirmDialog
		title="¿Eliminar esta nota?"
		text="Esta acción no se puede deshacer."
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
		gap: 10px;
		background: var(--surface-1);
		border-radius: var(--radius-md);
		padding: var(--space-sm) 10px;
		user-select: none;
		-webkit-user-select: none;
	}

	.play {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		color: var(--text-primary);
		position: relative;
	}

	/* 44px minimum tap target via an invisible halo. */
	.play::after,
	.action::after {
		content: '';
		position: absolute;
		inset: -12px;
	}

	.meta {
		display: inline-flex;
		align-items: baseline;
		gap: var(--space-sm);
		flex: 1;
		min-width: 0;
		text-align: left;
	}

	.duration {
		font-size: 12px;
		color: var(--text-secondary);
	}

	.transcript {
		font-size: 12px;
		color: var(--text-secondary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.action {
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		color: var(--text-muted);
	}

	.action.saved {
		color: var(--text-primary);
	}

	.delete {
		color: var(--text-danger);
	}
</style>
