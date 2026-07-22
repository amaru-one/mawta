<script lang="ts">
	import type { Participation } from '$lib/types';

	interface Props {
		value: Participation | null;
		disabled?: boolean;
		onchange: (value: Participation) => void;
	}

	let { value, disabled = false, onchange }: Props = $props();

	let pulsing = $state(false);

	const LABELS: Record<Participation, string> = {
		0: 'none',
		1: 'low',
		2: 'good',
		3: 'excellent'
	};

	const filled = $derived(value ?? 0);

	function cycle(): void {
		if (disabled) return;
		const next = (((value ?? 0) + 1) % 4) as Participation;
		onchange(next);
		pulsing = true;
		setTimeout(() => (pulsing = false), 200);
	}

	function fillClass(i: number): string {
		if (i >= filled) return 'empty';
		if (filled === 1) return 'low';
		if (filled === 2) return 'good';
		return 'excellent';
	}
</script>

<button
	class="circles pressable"
	class:disabled
	{disabled}
	onclick={cycle}
	aria-label={`Participation: ${value === null ? 'not set' : LABELS[filled as Participation]} — tap to change`}
	title={value === null ? 'Participation' : LABELS[filled as Participation]}
>
	{#each [0, 1, 2] as i (i)}
		<span class="circle {fillClass(i)}" class:pulse={pulsing && i < filled}></span>
	{/each}
</button>

<style>
	.circles {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		min-width: 44px;
		min-height: 44px;
		justify-content: center;
		border-radius: var(--radius-md);
		padding: 0 var(--space-xs);
	}

	.circles:active:not(.disabled) {
		box-shadow: var(--shadow-primary);
	}

	.disabled {
		opacity: 0.4;
		cursor: default;
	}

	.circle {
		width: 24px;
		height: 24px;
		border-radius: 50%;
		background: var(--neutral-300);
		transition: background-color 150ms ease-out;
	}

	.circle.low {
		background: var(--primary);
	}

	.circle.good {
		background: var(--success);
	}

	.circle.excellent {
		background: var(--accent-warm);
	}

	.circle.pulse {
		animation: pulse-scale 200ms ease-out;
	}

	@media (max-width: 480px) {
		.circle {
			width: 20px;
			height: 20px;
		}
	}
</style>
