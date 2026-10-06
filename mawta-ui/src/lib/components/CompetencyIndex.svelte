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
			aria-label={`Competencia ${item.label}${item.hasLevel ? ', con nivel' : ''}`}
			aria-current={item.id === selectedId ? 'true' : undefined}
			onclick={() => pick(item.id)}
		>
			{item.label}
		</button>
	{/each}
</div>

<style>
	.index {
		overflow-x: auto;
		display: flex;
		align-items: flex-end;
		border-bottom: 1px solid var(--mw-line);
	}

	.item {
		min-width: 40px;
		min-height: 48px;
		flex-shrink: 0;
		display: block;
		padding: 13px 10px 9px;
		border-bottom: 2px solid transparent;
		font-size: var(--mw-type-title-size);
		font-weight: 600;
		line-height: 1;
		color: var(--mw-ink-muted);
	}

	.item.short {
		padding-bottom: 10px;
		font-size: var(--mw-type-small-size);
		letter-spacing: 0.04em;
		font-family: var(--mw-font-sans);
	}

	.item.has {
		color: var(--mw-ink-secondary);
	}

	.item.on {
		border-bottom-color: var(--mw-accent);
		color: var(--mw-accent);
	}

	.split {
		width: 0.5px;
		height: 18px;
		margin: 0 10px 12px;
		background: var(--mw-line);
	}
</style>
