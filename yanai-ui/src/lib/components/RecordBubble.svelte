<script lang="ts" module>
	// Phases: idle → pressing (<COMMIT_MS, may still be a mis-tap) → recording.
	export type RecordPhase = 'idle' | 'pressing' | 'recording';
</script>

<script lang="ts">
	import { onMount } from 'svelte';
	import { hapticRecordStart, hapticSuccess } from '$lib/haptics';
	import { MAX_RECORD_SEC, startRecording, type ActiveRecording } from '$lib/recorder';

	interface Props {
		/**
		 * A student is chosen. Recording is gated on this and nothing else — the
		 * bubble takes the saturated gradient and the control becomes pressable.
		 * False renders the drained waiting gradient and disables it.
		 */
		armed: boolean;
		/** One completed hold. `durationSec` is the real held time, capped at MAX_RECORD_SEC. */
		onrecorded: (blob: Blob, durationSec: number) => void;
		/**
		 * Bound OUT only. The owning screen renders the hint, the countdown and
		 * the topbar REC marker from these; this component is their sole writer.
		 */
		phase?: RecordPhase;
		elapsedSec?: number;
	}

	let { armed, onrecorded, phase = $bindable('idle'), elapsedSec = $bindable(0) }: Props = $props();

	// url(#…) resolves document-globally, so every filter and gradient id has to
	// be unique per instance or a second mount silently steals the first's.
	const uid = $props.id();

	let recording: ActiveRecording | null = null;
	let pressedAt = 0;
	let commitTimer: ReturnType<typeof setTimeout> | undefined;
	let tickTimer: ReturnType<typeof setInterval> | undefined;
	let pressId = 0;

	const COMMIT_MS = 400;

	// SMIL cannot be switched off by a media query, so reduced motion is handled
	// by not rendering the <animate> children at all.
	let reducedMotion = $state(false);
	onMount(() => {
		reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
	});

	const RADIUS = 106;
	const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
	const arc = $derived(Math.min(elapsedSec / MAX_RECORD_SEC, 1) * CIRCUMFERENCE);

	const filterKey = $derived(phase === 'recording' ? 'rec' : armed ? 'armed' : 'idle');

	async function press(event: PointerEvent): Promise<void> {
		if (phase !== 'idle' || !armed) return;
		event.preventDefault();
		try {
			(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
		} catch {
			// Pointer already released (or synthetic event) — capture is best-effort.
		}
		void begin();
	}

	async function begin(): Promise<void> {
		const id = ++pressId;
		phase = 'pressing';
		pressedAt = performance.now();
		elapsedSec = 0;

		commitTimer = setTimeout(() => {
			if (pressId !== id || phase !== 'pressing') return;
			phase = 'recording';
			hapticRecordStart();
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
		elapsedSec = 0;

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

	// Stops on its own at the cap, regardless of whether the finger is still
	// down. release() is a no-op afterward (phase is already 'idle').
	async function autoStop(): Promise<void> {
		if (phase !== 'recording') return;
		clearInterval(tickTimer);
		const active = recording;
		recording = null;
		phase = 'idle';
		elapsedSec = 0;
		if (!active) return;

		const blob = await active.stop();
		if (blob) {
			hapticSuccess();
			onrecorded(blob, MAX_RECORD_SEC);
		}
	}

	// A button that only answers to pointers is a button in name only.
	function keyDown(event: KeyboardEvent): void {
		if (event.repeat || (event.key !== ' ' && event.key !== 'Enter')) return;
		if (phase !== 'idle' || !armed) return;
		event.preventDefault();
		void begin();
	}

	function keyUp(event: KeyboardEvent): void {
		if (event.key !== ' ' && event.key !== 'Enter') return;
		void release();
	}
</script>

<div class="bubble">
	<svg
		class="art"
		class:idle={!armed}
		class:armed={armed && phase !== 'recording'}
		class:rec={phase === 'recording'}
		class:still={reducedMotion}
		viewBox="0 0 360 360"
		aria-hidden="true"
	>
		<defs>
			<!-- userSpaceOnUse regions: an animated radius churns the bounding box
			     every frame, and a fixed region is both cheaper and deterministic. -->
			<filter id="{uid}-idle" filterUnits="userSpaceOnUse" x="60" y="60" width="240" height="240">
				<feTurbulence type="fractalNoise" baseFrequency="0.012" numOctaves="1" seed="5" result="n">
					{#if !reducedMotion}
						<animate
							attributeName="baseFrequency"
							values="0.010;0.016;0.010"
							dur="14s"
							repeatCount="indefinite"
						/>
					{/if}
				</feTurbulence>
				<feDisplacementMap in="SourceGraphic" in2="n" scale="12" />
			</filter>

			<filter id="{uid}-armed" filterUnits="userSpaceOnUse" x="60" y="60" width="240" height="240">
				<feTurbulence type="fractalNoise" baseFrequency="0.010" numOctaves="1" seed="3" result="n">
					{#if !reducedMotion}
						<animate
							attributeName="baseFrequency"
							values="0.008;0.015;0.008"
							dur="8s"
							repeatCount="indefinite"
						/>
					{/if}
				</feTurbulence>
				<feDisplacementMap in="SourceGraphic" in2="n" scale="12" />
			</filter>

			<filter id="{uid}-rec" filterUnits="userSpaceOnUse" x="60" y="60" width="240" height="240">
				<feTurbulence type="fractalNoise" baseFrequency="0.008" numOctaves="1" seed="2" result="n">
					{#if !reducedMotion}
						<animate
							attributeName="baseFrequency"
							values="0.007;0.012;0.007"
							dur="1.9s"
							repeatCount="indefinite"
						/>
					{/if}
				</feTurbulence>
				<feDisplacementMap in="SourceGraphic" in2="n" scale="14" />
			</filter>

			<!-- The ripples get a gentler wobble than the bubble: long wavelength,
			     short displacement, so they read as circles that breathe. -->
			<filter id="{uid}-ring" filterUnits="userSpaceOnUse" x="0" y="0" width="360" height="360">
				<feTurbulence type="fractalNoise" baseFrequency="0.007" numOctaves="1" seed="19" result="n">
					<animate
						attributeName="baseFrequency"
						values="0.006;0.010;0.006"
						dur="4s"
						repeatCount="indefinite"
					/>
				</feTurbulence>
				<feDisplacementMap in="SourceGraphic" in2="n" scale="7" />
			</filter>

			<!-- The accent lightened and deepened; no new colour enters the palette. -->
			<linearGradient id="{uid}-fill" x1="0%" y1="0%" x2="100%" y2="100%">
				<stop offset="0%" stop-color={armed ? '#8286e3' : '#eef0fc'} />
				<stop offset="52%" stop-color={armed ? '#5b5fc7' : '#dcdef4'} />
				<stop offset="100%" stop-color={armed ? '#4145a8' : '#c3c6ea'} />
			</linearGradient>
		</defs>

		{#if phase === 'recording' && !reducedMotion}
			<g filter="url(#{uid}-ring)" fill="none" stroke="#5b5fc7" stroke-width="1.25">
				<circle cx="180" cy="180" r="96" stroke-opacity="0.26">
					<animate attributeName="r" values="92;168" dur="2.7s" repeatCount="indefinite" />
					<animate
						attributeName="stroke-opacity"
						values="0.26;0"
						dur="2.7s"
						repeatCount="indefinite"
					/>
				</circle>
				<circle cx="180" cy="180" r="96" stroke-opacity="0.26">
					<animate
						attributeName="r"
						values="92;168"
						dur="2.7s"
						begin="1.35s"
						repeatCount="indefinite"
					/>
					<animate
						attributeName="stroke-opacity"
						values="0.26;0"
						dur="2.7s"
						begin="1.35s"
						repeatCount="indefinite"
					/>
				</circle>
			</g>
		{/if}

		<circle cx="180" cy="180" r="88" fill="url(#{uid}-fill)" filter="url(#{uid}-{filterKey})" />

		{#if phase === 'recording'}
			<!-- The gauge: crisp and unfiltered against the deforming bubble. One
			     full turn is the cap, so time left reads as an angle. -->
			<circle
				cx="180"
				cy="180"
				r={RADIUS}
				fill="none"
				stroke="#5b5fc7"
				stroke-opacity="0.14"
				stroke-width="3"
			/>
			{#if elapsedSec > 0.1}
				<circle
					cx="180"
					cy="180"
					r={RADIUS}
					fill="none"
					stroke="#5b5fc7"
					stroke-width="3"
					stroke-linecap="round"
					transform="rotate(-90 180 180)"
					stroke-dasharray="{arc} {CIRCUMFERENCE - arc}"
				/>
			{/if}
		{/if}
	</svg>

	<button
		class="hit"
		onpointerdown={press}
		onpointerup={release}
		onpointercancel={release}
		onlostpointercapture={release}
		onkeydown={keyDown}
		onkeyup={keyUp}
		oncontextmenu={(e) => e.preventDefault()}
		disabled={!armed}
		aria-pressed={phase === 'recording'}
		aria-label={armed
			? 'Mantén presionado para grabar una nota de voz'
			: 'Elige un alumno para poder grabar'}
	></button>
</div>

<style>
	.bubble {
		position: absolute;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		width: 360px;
		height: 360px;
		z-index: 1;
	}

	.art {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		overflow: visible;
		pointer-events: none;
		user-select: none;
	}

	.art.idle:not(.still) {
		animation: breathe-idle 14s ease-in-out infinite;
	}

	.art.armed:not(.still) {
		animation: breathe-armed 9s ease-in-out infinite;
	}

	.art.rec:not(.still) {
		animation: breathe-rec 2.2s ease-in-out infinite;
	}

	/* A generous circular target over the bubble. touch-action: none is required —
	   `manipulation` still lets a hold that drifts a few px turn into a pan, which
	   cancels the pointer and eats the note. Deliberately NOT .pressable: its
	   :active scale composes with the breathe keyframes and the bubble jumps. */
	.hit {
		position: absolute;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		width: 220px;
		height: 220px;
		border-radius: 50%;
		background: transparent;
		touch-action: none;
		user-select: none;
		-webkit-user-select: none;
		-webkit-touch-callout: none;
	}

	.hit:disabled {
		cursor: default;
	}

	.hit:focus-visible {
		outline: 2px solid var(--text-accent);
		outline-offset: 4px;
	}

	/* .art fills .bubble with inset:0 — the centring translate belongs to the
	   parent, so these scale only. */
	@keyframes breathe-idle {
		0%,
		100% {
			transform: scale(1);
		}
		50% {
			transform: scale(1.015);
		}
	}

	@keyframes breathe-armed {
		0%,
		100% {
			transform: scale(1);
		}
		50% {
			transform: scale(1.025);
		}
	}

	@keyframes breathe-rec {
		0%,
		100% {
			transform: scale(1);
		}
		50% {
			transform: scale(1.06);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.art {
			animation: none !important;
		}
	}
</style>
