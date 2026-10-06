<script lang="ts" module>
	export type RecordPhase = 'idle' | 'pressing' | 'recording';
</script>

<script lang="ts">
	import { Icon, Notice } from '$lib/design-system';
	import { onDestroy } from 'svelte';
	import { hapticRecordStart, hapticSuccess } from '$lib/haptics';
	import {
		MAX_RECORD_SEC,
		startRecording,
		releaseMicrophone,
		type ActiveRecording,
	} from '$lib/recorder';
	let {
		armed,
		onrecorded,
		phase = $bindable('idle'),
		elapsedSec = $bindable(0),
	}: {
		armed: boolean;
		onrecorded: (blob: Blob, durationSec: number) => void;
		phase?: RecordPhase;
		elapsedSec?: number;
	} = $props();
	const COMMIT_MS = 400;
	let recording: ActiveRecording | null = null;
	let pressedAt = 0;
	let pressId = 0;
	let alive = true;
	let error = $state('');
	let commitTimer: ReturnType<typeof setTimeout> | undefined;
	let tickTimer: ReturnType<typeof setInterval> | undefined;
	function reset() {
		clearTimeout(commitTimer);
		clearInterval(tickTimer);
		phase = 'idle';
		elapsedSec = 0;
	}
	function cancel() {
		++pressId;
		recording?.cancel();
		recording = null;
		reset();
	}
	async function begin() {
		if (!armed || phase !== 'idle') return;
		const id = ++pressId;
		error = '';
		phase = 'pressing';
		pressedAt = performance.now();
		elapsedSec = 0;
		commitTimer = setTimeout(() => {
			if (id !== pressId || !alive) return;
			phase = 'recording';
			hapticRecordStart();
			tickTimer = setInterval(() => {
				elapsedSec = Math.min((performance.now() - pressedAt) / 1000, MAX_RECORD_SEC);
				if (elapsedSec >= MAX_RECORD_SEC) void release();
			}, 100);
		}, COMMIT_MS);
		try {
			const active = await startRecording();
			if (id !== pressId || !alive) {
				active?.cancel();
				if (!alive) releaseMicrophone();
				return;
			}
			if (!active) throw new Error('microphone unavailable');
			recording = active;
		} catch {
			if (id !== pressId || !alive) return;
			cancel();
			error = 'No se pudo acceder al micrófono. Revisa el permiso e intenta de nuevo.';
		}
	}
	async function release() {
		if (phase === 'idle') return;
		++pressId;
		const duration = Math.min((performance.now() - pressedAt) / 1000, MAX_RECORD_SEC);
		const committed = phase === 'recording' && duration * 1000 >= COMMIT_MS;
		const active = recording;
		recording = null;
		reset();
		if (!active) return;
		if (!committed) {
			active.cancel();
			return;
		}
		try {
			const blob = await active.stop();
			if (blob && alive) {
				hapticSuccess();
				onrecorded(blob, duration);
			}
		} catch {
			if (alive) error = 'No se pudo guardar la grabación. Intenta de nuevo.';
		}
	}
	function press(event: PointerEvent) {
		if (!armed || phase !== 'idle' || event.button !== 0) return;
		event.preventDefault();
		try {
			(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
		} catch {
			/* Capture is best effort. */
		}
		void begin();
	}
	function keyDown(event: KeyboardEvent) {
		if (![' ', 'Enter'].includes(event.key)) return;
		event.preventDefault();
		if (!event.repeat) void begin();
	}
	function keyUp(event: KeyboardEvent) {
		if ([' ', 'Enter'].includes(event.key)) {
			event.preventDefault();
			void release();
		}
	}
	onDestroy(() => {
		alive = false;
		cancel();
		releaseMicrophone();
	});
</script>

<svelte:window onblur={cancel} />
<div class="recording-control">
	<button
		type="button"
		class="record"
		class:active={phase === 'recording'}
		disabled={!armed}
		onpointerdown={press}
		onpointerup={release}
		onpointercancel={release}
		onlostpointercapture={release}
		onkeydown={keyDown}
		onkeyup={keyUp}
		onblur={cancel}
		oncontextmenu={(event) => event.preventDefault()}
		aria-pressed={phase === 'recording'}
		aria-label={armed
			? 'Mantén presionado para grabar una nota de voz'
			: 'Elige un alumno para poder grabar'}
	>
		<Icon name="mic" size={32} /><span
			>{phase === 'recording' ? 'Suelta para guardar' : 'Mantén para grabar'}</span
		>
		<span class="elapsed"
			>{phase === 'recording'
				? `${Math.floor(elapsedSec)} / ${MAX_RECORD_SEC} s`
				: `Hasta ${MAX_RECORD_SEC} segundos`}</span
		>
	</button>
	<progress max={MAX_RECORD_SEC} value={elapsedSec} aria-label="Tiempo de grabación"></progress>
	{#if error}<Notice variant="danger" live>{error}</Notice>{/if}
</div>

<style>
	.recording-control {
		display: grid;
		gap: var(--mw-space-3);
		margin: var(--mw-space-6) 0;
	}
	.record {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--mw-space-3);
		width: 100%;
		min-height: 160px;
		border: 0;
		border-radius: var(--mw-radius-lg);
		padding: var(--mw-space-6);
		background: var(--mw-accent);
		color: var(--mw-on-accent);
		font-weight: 700;
		touch-action: none;
		user-select: none;
		-webkit-user-select: none;
		-webkit-touch-callout: none;
	}
	.record.active {
		background: var(--mw-accent-pressed);
	}
	.record:disabled {
		background: var(--mw-surface-tint);
		color: var(--mw-ink-muted);
	}
	.elapsed {
		font-size: var(--mw-type-small-size);
		font-weight: 500;
	}
	progress {
		width: 100%;
		height: 8px;
		border: 0;
		border-radius: var(--mw-radius-sm);
		overflow: hidden;
		background: var(--mw-line);
		accent-color: var(--mw-accent);
	}
	progress::-webkit-progress-bar {
		background: var(--mw-line);
	}
	progress::-webkit-progress-value {
		background: var(--mw-accent);
	}
	progress::-moz-progress-bar {
		background: var(--mw-accent);
	}
</style>
