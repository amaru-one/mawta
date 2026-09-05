<script lang="ts">
	// The competency index: the control that scopes a whole screen to one
	// competencia. Numerals, not pills — the state is darkness, and the current
	// one carries the only 2px stroke in the header.
	//
	// What "has a level" means is the caller's business and differs by screen: on
	// the class list it is "closed for the whole class", on a student's screen it
	// is "this student has a level here". The component only renders the three
	// states.
	import { hapticTap } from '$lib/haptics';
	import type { CompetencyIndexItem } from '$lib/types';

	interface Props {
		items: CompetencyIndexItem[];
		selectedId: string;
		onselect: (id: string) => void;
	}

	let { items, selectedId, onselect }: Props = $props();

	// Transversales are adscribed to no área, so they sit past a hairline rather
	// than continuing the área's numbering.
	const firstTransversalIndex = $derived(items.findIndex((i) => i.kind === 'transversal'));

	function pick(id: string): void {
		if (id === selectedId) return;
		hapticTap();
		onselect(id);
	}
</script>

<div class="index">
	{#each items as item, i (item.id)}
		{#if i === firstTransversalIndex && i > 0}
			<span class="split" aria-hidden="true"></span>
		{/if}
		<button
			type="button"
			class="item pressable"
			class:short={item.kind === 'transversal'}
			class:has={item.hasLevel}
			class:on={item.id === selectedId}
			aria-current={item.id === selectedId ? 'true' : undefined}
			onclick={() => pick(item.id)}
		>
			{item.label}
		</button>
	{/each}
</div>

<style>
	.index {
		display: flex;
		align-items: flex-end;
		border-bottom: 0.5px solid var(--border);
	}

	/* The numeral is 20px but the target is not: this padding is what puts the
	   row at 44px and spaces the numerals 20px apart without a `gap`. */
	.item {
		display: block;
		padding: 13px 10px 9px;
		border-bottom: 2px solid transparent;
		font-size: 20px;
		font-weight: 600;
		line-height: 1;
		color: var(--text-faint);
	}

	.item.short {
		padding-bottom: 10px;
		font-size: 13px;
		letter-spacing: 0.04em;
		font-family: var(--font-mono);
	}

	.item.has {
		color: var(--text-secondary);
	}

	.item.on {
		border-bottom-color: var(--fill-primary);
		color: var(--text-primary);
	}

	.split {
		width: 0.5px;
		height: 18px;
		margin: 0 10px 12px;
		background: var(--border);
	}
</style>
