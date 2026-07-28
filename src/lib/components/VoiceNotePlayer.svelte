<script lang="ts">
	import { onDestroy } from 'svelte';
	import { fly, scale } from 'svelte/transition';
	import { audioContext, blobDuration, decodeBlob, formatDuration } from '$lib/recorder';
	import type { Note } from '$lib/types';

	interface Props {
		note: Note;
		knownDuration?: number;
		ondelete: (note: Note) => void;
		onsave: (note: Note) => void;
	}

	let { note, knownDuration, ondelete, onsave }: Props = $props();

	let playing = $state(false);
	let position = $state(0);
	let measuredDuration = $state(0);
	let isSaved = $state(false);
	let showDeleteConfirm = $state(false);

	const duration = $derived(knownDuration ?? measuredDuration);

	let buffer: AudioBuffer | null = null;
	let source: AudioBufferSourceNode | null = null;
	let startedAt = 0;
	let pausedOffset = 0;
	let stopping = false;
	let posTimer: ReturnType<typeof setInterval> | undefined;

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

	onDestroy(() => {
		clearInterval(posTimer);
		if (source) {
			stopping = true;
			source.stop();
		}
	});
</script>

<div
	class="note"
	in:fly={{ x: -20, duration: 150 }}
	out:fly={{ x: 100, duration: 200 }}
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

	<div class="actions">
		<button
			class="save pressable"
			class:saved={isSaved}
			onclick={() => {
				onsave(note);
				isSaved = true;
			}}
			aria-label="Save note"
			title="Save note"
		>
			<svg viewBox="0 0 24 24" fill="currentColor" class="diskette-icon">
				<path d="M17 3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V7l-4-4zm-5 16c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm3-10H5V5h10v4z" />
			</svg>
		</button>
		<button
			class="delete pressable"
			onclick={() => (showDeleteConfirm = true)}
			aria-label="Delete note"
			title="Delete note"
		>
			<svg viewBox="0 0 24 24" fill="currentColor" class="trash-icon">
				<path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-9l-1 1H5v2h14V4z" />
			</svg>
		</button>
	</div>

	{#if showDeleteConfirm}
		<div
			class="delete-modal"
			in:scale={{ start: 0.95, duration: 150 }}
			out:scale={{ start: 0.95, duration: 150 }}
			onkeydown={(e) => e.key === 'Escape' && (showDeleteConfirm = false)}
			role="alertdialog"
			aria-modal="true"
			aria-labelledby="delete-title"
			tabindex="0"
		>
			<div
				class="modal-backdrop"
				onclick={() => (showDeleteConfirm = false)}
				onkeydown={(e) => e.key === 'Escape' && (showDeleteConfirm = false)}
				role="button"
				tabindex="-1"
				aria-label="Close confirmation dialog"
			></div>
			<div class="modal-content">
				<p class="modal-title" id="delete-title">Delete this note?</p>
				<p class="modal-text">This action cannot be undone.</p>
				<div class="modal-actions">
					<button
						class="modal-cancel pressable"
						onclick={() => (showDeleteConfirm = false)}
					>
						Cancel
					</button>
					<button
						class="modal-delete pressable"
						onclick={() => {
							ondelete(note);
							showDeleteConfirm = false;
						}}
					>
						Delete
					</button>
				</div>
			</div>
		</div>
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

	.actions {
		display: flex;
		gap: var(--space-xs);
		margin-left: auto;
	}

	@keyframes save-pulse {
		0%, 100% {
			transform: scale(1);
		}
		50% {
			transform: scale(1.2);
		}
	}

	.save {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		color: white;
		background: var(--gray-400);
		border: none;
		border-radius: 6px;
		cursor: pointer;
		transition: background-color 150ms ease-out;
		padding: 0;
		animation: save-pulse 0.6s ease-in-out infinite;
	}

	.save svg {
		width: 16px;
		height: 16px;
	}

	.save:hover {
		background: var(--gray-500);
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
	}

	.save:active {
		transform: scale(0.92);
	}

	.save.saved {
		background: var(--action-save);
		animation: none;
	}

	.save.saved:hover {
		background: var(--action-save-dark);
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
	}

	.delete {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		color: white;
		background: var(--action-delete);
		border: none;
		border-radius: 6px;
		cursor: pointer;
		transition: all 150ms ease-out;
		padding: 0;
	}

	.delete svg {
		width: 16px;
		height: 16px;
	}

	.delete:hover {
		background: var(--action-delete-dark);
		box-shadow: 0 2px 8px rgba(204, 42, 42, 0.3);
	}

	.delete:active {
		transform: scale(0.92);
	}

	.delete-modal {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
	}

	.modal-backdrop {
		position: absolute;
		inset: 0;
		background: rgba(0, 0, 0, 0.5);
		cursor: pointer;
	}

	.modal-content {
		position: relative;
		background: white;
		border-radius: 12px;
		padding: 24px;
		max-width: 320px;
		box-shadow: 0 20px 25px rgba(0, 0, 0, 0.15);
	}

	.modal-title {
		margin: 0 0 8px;
		font-size: 16px;
		font-weight: 700;
		color: var(--neutral-900);
	}

	.modal-text {
		margin: 0 0 20px;
		font-size: 14px;
		color: var(--neutral-600);
	}

	.modal-actions {
		display: flex;
		gap: 12px;
		justify-content: flex-end;
	}

	.modal-cancel {
		padding: 10px 16px;
		min-height: 36px;
		border-radius: 6px;
		background: var(--gray-200);
		color: var(--neutral-900);
		font-size: 14px;
		font-weight: 600;
		cursor: pointer;
		transition: all 150ms ease-out;
		border: none;
	}

	.modal-cancel:hover {
		background: var(--gray-300);
	}

	.modal-cancel:active {
		transform: scale(0.95);
	}

	.modal-delete {
		padding: 10px 16px;
		min-height: 36px;
		border-radius: 6px;
		background: var(--action-delete);
		color: white;
		font-size: 14px;
		font-weight: 600;
		cursor: pointer;
		transition: all 150ms ease-out;
		border: none;
	}

	.modal-delete:hover {
		background: var(--action-delete-dark);
	}

	.modal-delete:active {
		transform: scale(0.95);
	}
</style>
