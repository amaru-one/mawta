<script lang="ts">
	import type { Tier } from '$lib/grades';
	import LevelBadge from './LevelBadge.svelte';

	interface Props {
		level: Tier | null;
		disabled?: boolean;
		/** Rendered smaller for criterio rows, full size for a competency. */
		size?: number;
		onselect: (level: Tier) => void;
	}

	let { level, disabled = false, size = 32, onselect }: Props = $props();

	// CNEB descending-quality order, matching how the norm itself lists them.
	const TIERS: Tier[] = ['AD', 'A', 'B', 'C'];
</script>

<div class="picker row">
	{#each TIERS as t (t)}
		<button
			type="button"
			class="option pressable"
			class:selected={level === t}
			{disabled}
			onclick={() => onselect(t)}
			aria-pressed={level === t}
			aria-label={`Nivel ${t}`}
		>
			<LevelBadge tier={t} {size} />
		</button>
	{/each}
</div>

<style>
	.picker {
		gap: var(--space-sm);
	}

	.option {
		padding: 2px;
		border: none;
		background: none;
		border-radius: 8px;
		flex-shrink: 0;
	}

	.option.selected {
		outline: 2px solid var(--fill-primary);
		outline-offset: 2px;
	}

	.option:disabled {
		opacity: 0.5;
		cursor: default;
	}
</style>
