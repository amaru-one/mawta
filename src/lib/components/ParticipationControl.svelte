<script lang="ts">
	import type { Participation } from '$lib/types';

	interface Props {
		value: Participation | null;
		disabled?: boolean;
		onchange: (value: Participation) => void;
	}

	let { value, disabled = false, onchange }: Props = $props();

	let pulsing = $state(false);

	const filled = $derived(value ?? 0);

	function cycle(): void {
		if (disabled) return;
		const next = (((value ?? 0) + 1) % 4) as Participation;
		onchange(next);
		pulsing = true;
		setTimeout(() => (pulsing = false), 200);
	}
</script>

<button
	class="dots pressable"
	class:disabled
	{disabled}
	onclick={cycle}
	aria-label={`Participation: ${filled === 0 ? 'not rated' : `${filled} of 3`} — tap to change`}
	title={filled === 0 ? 'Participation' : `${filled}/3`}
>
	{#each [1, 2, 3] as i (i)}
		<span class="dot" class:filled={i <= filled} class:pulse={pulsing && i <= filled}></span>
	{/each}
</button>

<style>
	.dots {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		min-width: 44px;
		min-height: 44px;
		justify-content: center;
		border-radius: var(--radius-md);
		padding: 0 var(--space-xs);
	}

	.dots:active:not(.disabled) {
		box-shadow: var(--shadow-primary);
	}

	.disabled {
		opacity: 0.4;
		cursor: default;
	}

	.dot {
		width: 12px;
		height: 12px;
		border-radius: 50%;
		background: var(--gray-300);
		transition: background-color 150ms ease-out;
	}

	.dot.filled {
		background: var(--gray-800);
	}

	.dot.pulse {
		animation: pulse-scale 200ms ease-out;
	}

	@media (max-width: 480px) {
		.dot {
			width: 10px;
			height: 10px;
		}
	}
</style>
