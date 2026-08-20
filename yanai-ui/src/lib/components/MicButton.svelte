<script lang="ts">
	import { hapticRecordStart, hapticSuccess } from '$lib/haptics';
	import { formatDuration, startRecording, type ActiveRecording } from '$lib/recorder';
	import Icon from './Icon.svelte';

	interface Props {
		hasNotes: boolean;
		onrecorded: (blob: Blob, durationSec: number) => void;
		onrecordingchange?: (recording: boolean) => void;
		disabled?: boolean;
	}

	let { hasNotes, onrecorded, onrecordingchange, disabled = false }: Props = $props();

	// Phases: idle → pressing (<400ms, may still be a mis-tap) → recording
	let phase = $state<'idle' | 'pressing' | 'recording'>('idle');
	let elapsedSec = $state(0);

	let recording: ActiveRecording | null = null;
	let pressedAt = 0;
	let commitTimer: ReturnType<typeof setTimeout> | undefined;
	let tickTimer: ReturnType<typeof setInterval> | undefined;
	let pressId = 0;

	const COMMIT_MS = 400;
	const MAX_RECORD_SEC = 60; // voice notes are capped at 1 minute (server-enforced too)

	async function press(event: PointerEvent): Promise<void> {
		if (phase !== 'idle' || disabled) return;
		event.preventDefault();
		try {
			(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
		} catch {
			// Pointer already released (or synthetic event) — capture is best-effort.
		}
		const id = ++pressId;
		phase = 'pressing';
		pressedAt = performance.now();
		elapsedSec = 0;

		commitTimer = setTimeout(() => {
			if (pressId !== id || phase !== 'pressing') return;
			phase = 'recording';
			hapticRecordStart();
			onrecordingchange?.(true);
			tickTimer = setInterval(() => {
				elapsedSec = (performance.now() - pressedAt) / 1000;
				if (elapsedSec >= MAX_RECORD_SEC) void autoStop();
			}, 100);
		}, COMMIT_MS);

		// Start capturing immediately so the recording contains the whole hold.
		recording = await startRecording();
		if (pressId !== id && recording) {
			// Released before the mic came up — discard.
			recording.cancel();
			recording = null;
		}
	}

	async function release(): Promise<void> {
		if (phase === 'idle') return;
		const id = ++pressId;
		void id;
		clearTimeout(commitTimer);
		clearInterval(tickTimer);
		const heldMs = performance.now() - pressedAt;
		const wasRecording = phase === 'recording';
		phase = 'idle';
		onrecordingchange?.(false);

		const active = recording;
		recording = null;
		if (!active) return;

		if (!wasRecording || heldMs < COMMIT_MS) {
			// Mis-tap: discard silently, no UI change.
			active.cancel();
			return;
		}

		const blob = await active.stop();
		if (blob) {
			hapticSuccess();
			onrecorded(blob, heldMs / 1000);
		}
	}

	// Stops the recording on its own once it hits MAX_RECORD_SEC, regardless
	// of whether the finger is still down. release() is a no-op afterward
	// (phase is already 'idle' by the time the pointer lifts).
	async function autoStop(): Promise<void> {
		if (phase !== 'recording') return;
		clearInterval(tickTimer);
		const active = recording;
		recording = null;
		phase = 'idle';
		onrecordingchange?.(false);
		if (!active) return;

		const blob = await active.stop();
		if (blob) {
			hapticSuccess();
			onrecorded(blob, MAX_RECORD_SEC);
		}
	}
</script>

<div class="mic-wrap">
	{#if phase === 'recording'}
		<span class="counter">{formatDuration(elapsedSec)}</span>
		<span class="hint">Suelta para guardar</span>
	{:else if phase === 'pressing'}
		<span class="hint">Mantén para grabar</span>
	{/if}
	<button
		class="circ mic pressable"
		class:has-notes={hasNotes}
		class:pressing={phase === 'pressing'}
		class:recording={phase === 'recording'}
		class:disabled
		onpointerdown={press}
		onpointerup={release}
		onpointercancel={release}
		oncontextmenu={(e) => e.preventDefault()}
		{disabled}
		aria-label={disabled
			? 'Marca la asistencia antes de grabar'
			: 'Mantén presionado para grabar una nota de voz'}
	>
		<Icon name="mic" size={14} />
	</button>
</div>

<style>
	.mic-wrap {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
	}

	.mic {
		position: relative;
		background: var(--surface-1);
		color: var(--text-muted);
	}

	/* 44px minimum tap target via an invisible halo. */
	.mic::after {
		content: '';
		position: absolute;
		inset: -9px;
	}

	/* Rows that already carry a note get the filled treatment. */
	.mic.has-notes {
		background: var(--text-primary);
		color: var(--surface-2);
	}

	.mic.disabled {
		opacity: 0.4;
		cursor: not-allowed;
		pointer-events: none;
	}

	.mic.pressing,
	.mic.recording {
		transform: scale(1.15);
		background: var(--fill-primary);
		color: var(--on-primary);
	}

	.mic.recording {
		animation: record-pulse 600ms ease-in-out infinite;
	}

	.counter {
		font-family: var(--font-mono);
		font-size: 13px;
		font-weight: 500;
		min-width: 38px;
		text-align: right;
	}

	.hint {
		font-size: 12px;
		color: var(--text-secondary);
		white-space: nowrap;
	}

	@media (max-width: 480px) {
		.hint {
			display: none;
		}
	}
</style>
