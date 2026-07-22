<script lang="ts">
	import { hapticRecordStart, hapticSuccess } from '$lib/haptics';
	import { formatDuration, startRecording, type ActiveRecording } from '$lib/recorder';

	interface Props {
		hasNotes: boolean;
		onrecorded: (blob: Blob, durationSec: number) => void;
		onrecordingchange?: (recording: boolean) => void;
	}

	let { hasNotes, onrecorded, onrecordingchange }: Props = $props();

	// Phases: idle → pressing (<400ms, may still be a mis-tap) → recording
	let phase = $state<'idle' | 'pressing' | 'recording'>('idle');
	let elapsedSec = $state(0);

	let recording: ActiveRecording | null = null;
	let pressedAt = 0;
	let commitTimer: ReturnType<typeof setTimeout> | undefined;
	let tickTimer: ReturnType<typeof setInterval> | undefined;
	let pressId = 0;

	const COMMIT_MS = 400;

	async function press(event: PointerEvent): Promise<void> {
		if (phase !== 'idle') return;
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
</script>

<div class="mic-wrap">
	{#if phase === 'recording'}
		<span class="counter">{formatDuration(elapsedSec)}</span>
		<span class="hint">Release to save</span>
	{:else if phase === 'pressing'}
		<span class="hint">Hold to record</span>
	{/if}
	<button
		class="mic pressable"
		class:pressing={phase === 'pressing'}
		class:recording={phase === 'recording'}
		onpointerdown={press}
		onpointerup={release}
		onpointercancel={release}
		oncontextmenu={(e) => e.preventDefault()}
		aria-label="Hold to record a voice note"
	>
		<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
			<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
			<path d="M19 10v2a7 7 0 0 1-14 0v-2" />
			<line x1="12" y1="19" x2="12" y2="22" />
		</svg>
		{#if hasNotes && phase === 'idle'}
			<span class="dot" aria-hidden="true"></span>
		{/if}
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
		width: 44px;
		height: 44px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border-radius: 50%;
		color: var(--neutral-600);
		background: var(--neutral-100);
		border: 2px solid transparent;
	}

	.mic:hover {
		background: var(--neutral-200);
	}

	.mic.pressing {
		transform: scale(1.1);
		color: var(--primary);
		border-color: var(--primary);
		box-shadow: 0 0 8px rgba(0, 117, 180, 0.5);
	}

	.mic.recording {
		transform: scale(1.1);
		color: var(--primary);
		border-color: var(--primary);
		box-shadow: 0 0 12px rgba(0, 117, 180, 0.6);
		animation: record-pulse 600ms ease-in-out infinite;
	}

	.dot {
		position: absolute;
		top: 2px;
		right: 2px;
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--accent-warm);
		border: 2px solid white;
	}

	.counter {
		font-family: var(--font-mono);
		font-size: 14px;
		font-weight: 700;
		color: var(--primary);
		min-width: 40px;
		text-align: right;
	}

	.hint {
		font-size: 12px;
		color: var(--neutral-600);
		white-space: nowrap;
	}

	@media (max-width: 480px) {
		.hint {
			display: none;
		}
	}
</style>
