<script lang="ts">
	// The numeric value of one piece of evidence, drawn to scale.
	//
	// A ruler rather than a field or a keypad because it is the only control
	// compact enough to sit permanently open on every evidence at once — which is
	// what let the screen drop its accordion. It also shows where this mark falls
	// in the range while the teacher is still deciding, which is how marking
	// actually goes: a position first, a number second.
	//
	// It is a line control on purpose. The only boxed control on the screen is the
	// competency level, because that is the official record and this is not.
	import { hapticTap } from '$lib/haptics';

	interface Props {
		value: number | null;
		max?: number;
		disabled?: boolean;

		onselect: (value: number) => void;
	}

	let { value, max = 20, disabled = false, onselect }: Props = $props();

	let track = $state<HTMLDivElement | null>(null);
	// Set while a drag is in flight so the readout follows the thumb without
	// writing a score on every pixel.
	let dragging = $state<number | null>(null);

	const shown = $derived(dragging ?? value);
	const ticks = $derived(Array.from({ length: max + 1 }, (_, i) => i));
	const midLabel = $derived(Math.round(max / 2));

	// Each tick owns an equal column, so the column under the finger *is* the
	// value — no nearest-tick search.
	function valueAt(clientX: number): number {
		if (track === null) return 0;
		const r = track.getBoundingClientRect();
		const t = (clientX - r.left) / r.width;
		return Math.max(0, Math.min(max, Math.floor(t * (max + 1))));
	}

	function down(e: PointerEvent): void {
		if (disabled) return;
		if (e.currentTarget instanceof HTMLElement) {
			e.currentTarget.setPointerCapture(e.pointerId);
		}
		dragging = valueAt(e.clientX);
	}

	function move(e: PointerEvent): void {
		if (disabled || dragging === null) return;
		const next = valueAt(e.clientX);
		if (next !== dragging) {
			dragging = next;
			hapticTap();
		}
	}

	function up(): void {
		if (disabled || dragging === null) return;
		const committed = dragging;
		dragging = null;
		if (committed !== value) onselect(committed);
	}

	function key(e: KeyboardEvent): void {
		if (disabled) return;
		const from = value ?? 0;
		if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
			e.preventDefault();
			onselect(Math.max(0, from - 1));
		} else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
			e.preventDefault();
			onselect(Math.min(max, from + 1));
		}
	}
</script>

<div class="ruler" class:off={disabled}>
	<span class="readout" class:empty={shown === null}>
		{shown ?? '—'}<span class="denom">/{max}</span>
	</span>

	<div
		bind:this={track}
		class="track"
		role="slider"
		tabindex={disabled ? -1 : 0}
		aria-label="Nota sobre {max}"
		aria-valuemin={0}
		aria-valuemax={max}
		aria-valuenow={shown ?? 0}
		aria-valuetext={shown === null ? 'Sin valorar' : `${shown} sobre ${max}`}
		aria-disabled={disabled}
		onpointerdown={down}
		onpointermove={move}
		onpointerup={up}
		onpointercancel={up}
		onkeydown={key}
	>
		<div class="ticks">
			{#each ticks as t (t)}
				{#if t === shown}
					<span class="col">
						<span class="dot"></span>
						<span class="bar on"></span>
					</span>
				{:else}
					<span class="col">
						<span class="bar" class:five={t % 5 === 0}></span>
					</span>
				{/if}
			{/each}
		</div>

		<div class="labels">
			{#each ticks as t (t)}
				<span class="lbl">
					{#if t === 0 || t === max || t === midLabel}{t}{/if}
				</span>
			{/each}
		</div>
	</div>
</div>

<style>
	.ruler {
		display: flex;
		align-items: flex-end;
		gap: 16px;
	}

	.ruler.off {
		opacity: 0.3;
		pointer-events: none;
	}

	.readout {
		flex-shrink: 0;
		width: 66px;
		font-size: var(--mw-type-title-size);
		font-weight: 600;
		line-height: 0.9;
		letter-spacing: -0.03em;
	}

	.readout.empty {
		color: var(--mw-ink-muted);
	}

	.denom {
		font-size: var(--mw-type-small-size);
		font-weight: 500;
		letter-spacing: 0;
		color: var(--mw-ink-muted);
	}

	.track {
		min-height: 48px;
		flex: 1;
		min-width: 0;
		touch-action: none;
		cursor: pointer;
	}

	.track:focus-visible {
		outline: 2px solid var(--mw-accent);
		outline-offset: 4px;
		border-radius: var(--mw-radius-sm);
	}

	.ticks {
		display: flex;
		align-items: flex-end;
		height: 36px;
	}

	.col {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: flex-end;
		gap: 4px;
	}

	.bar {
		width: 1px;
		height: 7px;
		background: var(--mw-ink-muted);
	}

	.bar.five {
		height: 12px;
		background: var(--mw-ink-secondary);
	}

	.bar.on {
		width: 3px;
		height: 24px;
		border-radius: 2px;
		background: var(--mw-accent);
	}

	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--mw-accent);
	}

	.labels {
		display: flex;
		margin-top: 6px;
	}

	.lbl {
		flex: 1 1 0;
		min-width: 0;
		white-space: nowrap;
		overflow-wrap: normal;
		text-align: center;
		font-size: var(--mw-type-label-size);
		color: var(--mw-ink-muted);
		font-family: var(--mw-font-sans);
	}
</style>
