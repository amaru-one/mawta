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

	// The gauge sits 16px outside the 232px orb, on the stage's own 360-unit
	// grid (1 unit = 1px), so the ring the teacher already sees becomes the
	// track the progress arc is drawn over.
	const RADIUS = 132;
	const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
	const arc = $derived(Math.min(elapsedSec / MAX_RECORD_SEC, 1) * CIRCUMFERENCE);

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

	// The orb turns on its vertical axis at one constant CSS duration (22s) and
	// speeds up for a hold by scaling *playback rate*, never by swapping
	// `animation-duration` — a duration change restarts the animation's phase,
	// which would make the orb visibly jump the instant a hold commits. Rate 8
	// (≈2.75s/turn) recording, rate 1 (22s/turn) otherwise — idle and armed spin
	// at the same slow tempo; only an actual recording is fast.
	const IDLE_RATE = 1;
	const REC_RATE = 8;

	let root: HTMLDivElement | null = null;

	function setSpin(rec: boolean): void {
		if (!root) return;
		const rate = rec ? REC_RATE : IDLE_RATE;
		for (const blob of root.querySelectorAll<HTMLElement>('.blob')) {
			for (const anim of blob.getAnimations()) {
				try {
					anim.updatePlaybackRate(rate);
				} catch {
					// Older engines lack updatePlaybackRate — a direct assignment
					// still takes effect, just without the smooth ramp.
					anim.playbackRate = rate;
				}
			}
		}
	}

	$effect(() => {
		setSpin(phase === 'recording');
	});
</script>

<div
	class="bubble"
	bind:this={root}
	class:idle={!armed}
	class:armed={armed && phase !== 'recording'}
	class:rec={phase === 'recording'}
	class:still={reducedMotion}
>
	<!-- Light spilling from the orb onto the page. It is what the frosted
	     surface has to refract: over flat white the glass would have nothing to
	     blur and would read as a solid disc. -->
	<div class="ambient" aria-hidden="true"></div>

	<!-- Four drifting lights under one translucent surface. The colour lives
	     below the glass, so what the teacher sees is the blur of it, never the
	     blobs themselves. -->
	<div class="orb" aria-hidden="true">
		<div class="colorfield">
			<span class="blob b1"></span>
			<span class="blob b2"></span>
			<span class="blob b3"></span>
			<span class="blob b4"></span>
		</div>
		<div class="glass"></div>
		<div class="specular"></div>
	</div>

	<svg class="gauge" viewBox="0 0 360 360" aria-hidden="true">
		<defs>
			<!-- The ripples get a gentle wobble: long wavelength, short
			     displacement, so they read as circles that breathe. -->
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
		</defs>

		{#if phase === 'recording' && !reducedMotion}
			<g class="ripples" filter="url(#{uid}-ring)">
				<circle cx="180" cy="180" r="120" stroke-opacity="0.26">
					<animate attributeName="r" values="120;168" dur="2.7s" repeatCount="indefinite" />
					<animate
						attributeName="stroke-opacity"
						values="0.26;0"
						dur="2.7s"
						repeatCount="indefinite"
					/>
				</circle>
				<circle cx="180" cy="180" r="120" stroke-opacity="0.26">
					<animate
						attributeName="r"
						values="120;168"
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

		<!-- The hairline ring is present in every state; while recording the arc
		     is drawn over it, so time left reads as an angle on a ring the
		     teacher was already looking at. One full turn is the cap. -->
		<circle class="track" cx="180" cy="180" r={RADIUS} />

		{#if phase === 'recording' && elapsedSec > 0.1}
			<circle
				class="arc"
				cx="180"
				cy="180"
				r={RADIUS}
				transform="rotate(-90 180 180)"
				stroke-dasharray="{arc} {CIRCUMFERENCE - arc}"
			/>
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
	/* The stage keeps its 360×360 box in every state. Where it is anchored, and
	   how much it is scaled on a short viewport, come from outside as variables
	   the owning screen sets on the stage — see that route's SPEC. */
	.bubble {
		position: absolute;
		top: var(--bubble-anchor, 50%);
		left: 50%;
		transform: translate(-50%, -50%) scale(var(--bubble-scale, 1));
		width: 360px;
		height: 360px;
		z-index: 1;
	}

	/* The rotation's tempo is NOT set here. One duration lives in CSS and the
	   state changes `playbackRate` instead (see `setSpin`), because swapping
	   `animation-duration` restarts the phase: the orb would jump the moment a
	   hold commits, which is exactly the seam this animation exists to avoid. */

	.ambient {
		position: absolute;
		top: 50%;
		left: 50%;
		width: 520px;
		height: 520px;
		transform: translate(-50%, -50%);
		border-radius: 50%;
		/* The rgba forms of --aurora-1 and --aurora-2. */
		background: radial-gradient(
			circle,
			rgba(124, 155, 255, 0.16) 0%,
			rgba(124, 247, 217, 0.1) 40%,
			transparent 68%
		);
		pointer-events: none;
		transition: opacity 400ms ease-out;
	}

	.bubble.idle .ambient {
		opacity: 0.3;
	}

	/* 232px inside the 360 stage; the gauge ring sits 16px outside it. */
	.orb {
		position: absolute;
		inset: 64px;
		border-radius: 50%;
		pointer-events: none;
		user-select: none;
	}

	.bubble.idle:not(.still) .orb {
		animation: breathe-idle 14s ease-in-out infinite;
	}

	.bubble.armed:not(.still) .orb {
		animation: breathe-armed 9s ease-in-out infinite;
	}

	.bubble.rec:not(.still) .orb {
		animation: breathe-rec 2.2s ease-in-out infinite;
	}

	.colorfield {
		position: absolute;
		inset: 0;
		border-radius: 50%;
		overflow: hidden;
		transition:
			filter 450ms ease-out,
			opacity 450ms ease-out;
	}

	/* Waiting for a student: the colour drains to a pale lilac but the movement
	   does not stop — a still orb reads as a broken one. Draining further makes
	   it white on white, which reads as nothing at all. */
	.bubble.idle .colorfield {
		filter: saturate(0.4) brightness(1.04);
		opacity: 0.85;
	}

	/* The four lights cross the orb on the same 22s loop, a quarter-turn apart,
	   so the field is never empty and never repeats a frame exactly. */
	.blob {
		position: absolute;
		left: 17%;
		width: 66%;
		height: 66%;
		border-radius: 50%;
		/* Scaled with the orb: the approved artboard's 18px over 272px. Blurring
		   further washes the four hues into one pale disc. */
		filter: blur(15px);
		mix-blend-mode: screen;
		animation-name: corriente;
		animation-duration: 22s;
		animation-timing-function: linear;
		animation-iteration-count: infinite;
	}

	.b1 {
		top: 17%;
		background: var(--aurora-1);
	}

	.b2 {
		top: 6%;
		background: var(--aurora-2);
		animation-delay: -5.5s;
	}

	.b3 {
		top: 26%;
		background: var(--aurora-3);
		animation-delay: -11s;
	}

	.b4 {
		top: 14%;
		background: var(--fill-accent);
		animation-delay: -16.5s;
	}

	/* The whole point of the surface: it blurs the colour below it *and* the
	   page behind it, which is what makes the orb read as glass rather than as
	   a printed gradient. */
	.glass {
		position: absolute;
		inset: 0;
		border-radius: 50%;
		background: rgba(255, 255, 255, 0.08);
		backdrop-filter: blur(16px) saturate(1.35);
		-webkit-backdrop-filter: blur(16px) saturate(1.35);
		box-shadow:
			inset 0 0 0 1px rgba(255, 255, 255, 0.5),
			inset 0 16px 36px rgba(255, 255, 255, 0.3),
			0 18px 36px rgba(35, 40, 90, 0.1);
	}

	.specular {
		position: absolute;
		top: 15%;
		left: 26%;
		width: 30%;
		height: 16%;
		border-radius: 50%;
		background: radial-gradient(ellipse, rgba(255, 255, 255, 0.85), transparent 70%);
		filter: blur(1px);
	}

	.gauge {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		overflow: visible;
		pointer-events: none;
		user-select: none;
	}

	.track {
		fill: none;
		stroke: var(--aurora-deep);
		stroke-opacity: 0.14;
		stroke-width: 1;
	}

	.arc {
		fill: none;
		stroke: var(--fill-accent);
		stroke-width: 3;
		stroke-linecap: round;
	}

	.ripples {
		fill: none;
		stroke: var(--fill-accent);
		stroke-width: 1.25;
	}

	/* The whole orb, so nothing that looks pressable is a dead zone.
	   touch-action: none is required — `manipulation` still lets a hold that
	   drifts a few px turn into a pan, which cancels the pointer and eats the
	   note. Deliberately NOT .pressable: its :active scale composes with the
	   breathe keyframes and the bubble jumps. */
	.hit {
		position: absolute;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		width: 232px;
		height: 232px;
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

	/* .orb fills .bubble with inset:56px — the centring translate belongs to the
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

	/* One light's whole loop: it enters compressed at the left edge (a sliver,
	   the way colour looks wrapping round the side of a sphere), widens to full
	   strength crossing the front, and exits compressed at the right. Four
	   copies offset a quarter-loop apart (see the .b1–.b4 delays) is what reads
	   as one continuous body turning rather than four blobs sliding past. */
	@keyframes corriente {
		0% {
			transform: translateX(-135%) scaleX(0.42);
			opacity: 0;
		}
		14% {
			opacity: 0.85;
		}
		50% {
			transform: translateX(0) scaleX(1);
			opacity: 0.85;
		}
		86% {
			opacity: 0.85;
		}
		100% {
			transform: translateX(135%) scaleX(0.42);
			opacity: 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.orb,
		.blob {
			animation: none !important;
		}
	}
</style>
