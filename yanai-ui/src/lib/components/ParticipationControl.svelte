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
	class="part pressable"
	class:disabled
	{disabled}
	onclick={cycle}
	aria-label={`Participación: ${filled === 0 ? 'sin calificar' : `${filled} de 3`} — toca para cambiar`}
	title={filled === 0 ? 'Participación' : `${filled}/3`}
>
	{#each [1, 2, 3] as i (i)}
		<span class:filled={i <= filled} class:pulse={pulsing && i <= filled}></span>
	{/each}
</button>

<style>
	.part {
		position: relative;
		align-items: center;
	}

	/* 44px minimum tap target via an invisible halo. */
	.part::after {
		content: '';
		position: absolute;
		inset: -16px -12px;
	}

	.part span {
		background: var(--border-strong);
		opacity: 0.35;
		transition:
			opacity 150ms ease-out,
			background-color 150ms ease-out;
	}

	.part span.filled {
		background: var(--text-primary);
		opacity: 1;
	}

	.part span.pulse {
		animation: pulse-scale 200ms ease-out;
	}

	.disabled {
		opacity: 0.4;
		cursor: default;
	}
</style>
