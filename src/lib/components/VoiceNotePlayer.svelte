<script lang="ts">
	import { onDestroy } from 'svelte';
	import { fly } from 'svelte/transition';
	import { audioContext, blobDuration, decodeBlob, formatDuration } from '$lib/recorder';
	import type { Note, NoteTag } from '$lib/types';

	interface Props {
		note: Note;
		knownDuration?: number;
		ondelete: (note: Note) => void;
		ontag: (note: Note, tag: NoteTag | undefined) => void;
	}

	let { note, knownDuration, ondelete, ontag }: Props = $props();

	let playing = $state(false);
	let position = $state(0);
	let measuredDuration = $state(0);
	let confirmingDelete = $state(false);

	const duration = $derived(knownDuration ?? measuredDuration);

	let buffer: AudioBuffer | null = null;
	let source: AudioBufferSourceNode | null = null;
	let startedAt = 0;
	let pausedOffset = 0;
	let stopping = false;
	let posTimer: ReturnType<typeof setInterval> | undefined;
	let holdTimer: ReturnType<typeof setTimeout> | undefined;

	const TAGS: NoteTag[] = ['academic', 'behavior', 'logistics'];
	const TAG_SHORT: Record<NoteTag, string> = { academic: 'A', behavior: 'B', logistics: 'L' };

	$effect(() => {
		if (!duration) {
			void blobDuration(note.audioBlob).then((d) => {
				if (d > 0) measuredDuration = d;
			});
		}
	});

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
		buffer ??= await decodeBlob(note.audioBlob);
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

	function holdStart(): void {
		holdTimer = setTimeout(() => {
			confirmingDelete = true;
		}, 500);
	}

	function holdEnd(): void {
		clearTimeout(holdTimer);
	}

	onDestroy(() => {
		clearInterval(posTimer);
		clearTimeout(holdTimer);
		if (source) {
			stopping = true;
			source.stop();
		}
	});
</script>

<div
	class="note"
	class:confirming={confirmingDelete}
	in:fly={{ x: -20, duration: 150 }}
	out:fly={{ x: 100, duration: 200 }}
	onpointerdown={holdStart}
	onpointerup={holdEnd}
	onpointercancel={holdEnd}
	oncontextmenu={(e) => e.preventDefault()}
	role="group"
	aria-label="Voice note"
>
	<button
		class="play pressable"
		class:active={playing}
		onclick={togglePlay}
		aria-label={playing ? 'Pause note' : 'Play note'}
	>
		{#if playing}
			<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true">
				<rect x="5" y="4" width="5" height="16" rx="1" />
				<rect x="14" y="4" width="5" height="16" rx="1" />
			</svg>
		{:else}
			<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true">
				<path d="M7 4.5v15a1 1 0 0 0 1.53.85l12-7.5a1 1 0 0 0 0-1.7l-12-7.5A1 1 0 0 0 7 4.5Z" />
			</svg>
		{/if}
	</button>

	<button class="meta pressable" onclick={togglePlay} aria-label="Play note">
		<span class="duration">
			{playing ? formatDuration(position) : formatDuration(duration)}
		</span>
		{#if note.transcript}
			<span class="transcript">“{note.transcript}”</span>
		{/if}
	</button>

	<span class="tags">
		{#each TAGS as tag (tag)}
			<button
				class="tag pressable"
				class:active={note.tag === tag}
				onclick={() => ontag(note, note.tag === tag ? undefined : tag)}
				aria-label={`Tag as ${tag}`}
				aria-pressed={note.tag === tag}
				title={tag}
			>
				{TAG_SHORT[tag]}
			</button>
		{/each}
	</span>

	{#if confirmingDelete}
		<button
			class="delete pressable"
			transition:fly={{ x: 40, duration: 200 }}
			onclick={() => ondelete(note)}
			aria-label="Delete note"
		>
			Delete
		</button>
		<button
			class="cancel pressable"
			onclick={() => (confirmingDelete = false)}
			aria-label="Keep note"
		>
			Keep
		</button>
	{/if}
</div>

<style>
	.note {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		padding: var(--space-xs) var(--space-sm);
		border-radius: var(--radius-sm);
		transition: background-color 150ms ease-out;
		user-select: none;
		-webkit-user-select: none;
	}

	.note.confirming {
		background: var(--danger-light);
	}

	.play {
		width: 28px;
		height: 28px;
		min-width: 28px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border-radius: 50%;
		background: var(--primary-light);
		color: var(--primary);
		position: relative;
	}

	.play::after {
		content: '';
		position: absolute;
		inset: -8px;
	}

	.play.active {
		background: var(--primary);
		color: white;
		box-shadow: var(--shadow-primary);
	}

	.meta {
		display: inline-flex;
		align-items: baseline;
		gap: var(--space-sm);
		min-width: 0;
		text-align: left;
	}

	.duration {
		font-family: var(--font-mono);
		font-size: 12px;
		font-weight: 700;
		color: var(--neutral-600);
	}

	.transcript {
		font-size: 12px;
		color: var(--neutral-700);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.tags {
		display: inline-flex;
		gap: var(--space-xs);
		margin-left: auto;
	}

	.tag {
		width: 22px;
		height: 22px;
		border-radius: var(--radius-sm);
		font-size: 11px;
		font-weight: 700;
		background: var(--neutral-100);
		color: var(--neutral-400);
		display: inline-flex;
		align-items: center;
		justify-content: center;
	}

	.tag.active {
		background: var(--accent-warm-light);
		color: var(--accent-warm);
	}

	.delete {
		font-size: 12px;
		font-weight: 700;
		color: var(--danger);
		background: white;
		border-radius: var(--radius-sm);
		padding: var(--space-xs) var(--space-sm);
		box-shadow: var(--shadow-sm);
	}

	.cancel {
		font-size: 12px;
		font-weight: 500;
		color: var(--neutral-600);
		padding: var(--space-xs) var(--space-sm);
	}
</style>
