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
		/** null = not valued yet. Rendered as a dash, never as a zero. */
		value: number | null;
		max?: number;
		disabled?: boolean;
		/** Fires once per commit (pointer release / key), never mid-drag. */
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
		{shown ?? '–'}<span class="denom">/{max}</span>
	</span>

	<div
		bind:this={track}
		class="track"
		role="slider"
		tabindex={disabled ? -1 : 0}
		aria-label="Nota sobre {max}"
		aria-valuemin={0}
		aria-valuemax={max}
		aria-valuenow={shown ?? undefined}
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

	/* Fixed width so a 1- and a 2-digit mark leave the ruler in the same place. */
	.readout {
		flex-shrink: 0;
		width: 66px;
		font-size: 44px;
		font-weight: 600;
		line-height: 0.9;
		letter-spacing: -0.03em;
	}

	.readout.empty {
		color: var(--text-faint);
	}

	.denom {
		font-size: 13px;
		font-weight: 500;
		letter-spacing: 0;
		color: var(--text-muted);
	}

	.track {
		flex: 1;
		min-width: 0;
		touch-action: none;
		cursor: pointer;
	}

	.track:focus-visible {
		outline: 2px solid var(--aurora-deep);
		outline-offset: 4px;
		border-radius: var(--radius-sm);
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
		background: var(--text-faint);
	}

	/* Every fifth mark is longer and carries a figure — the scale needs anchors
	   or it reads as texture. */
	.bar.five {
		height: 12px;
		background: var(--text-secondary);
	}

	.bar.on {
		width: 3px;
		height: 24px;
		border-radius: 2px;
		background: var(--aurora-deep);
	}

	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--aurora-deep);
	}

	.labels {
		display: flex;
		margin-top: 6px;
	}

	.lbl {
		flex: 1;
		text-align: center;
		font-size: 10px;
		color: var(--text-muted);
		font-family: var(--font-mono);
	}
</style>
