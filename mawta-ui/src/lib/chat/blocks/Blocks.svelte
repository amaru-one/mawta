<script lang="ts">
	import type { Block } from '../types';
	import { isErrorBlock, isTableBlock, isTextBlock } from '../types';
	import ErrorBlock from './ErrorBlock.svelte';
	import TableBlock from './TableBlock.svelte';
	import TextBlock from './TextBlock.svelte';
	let {
		blocks,
		streaming = false,
		onretry,
	}: { blocks: Block[]; streaming?: boolean; onretry?: () => void } = $props();
	// Protocol v1: a block type this UI does not know yet (e.g. grafico) is skipped.
	const lastText = $derived(blocks.findLastIndex(isTextBlock));
</script>

{#each blocks as block, i (i)}
	{#if isTextBlock(block)}
		<TextBlock md={block.md} streaming={streaming && i === lastText && i === blocks.length - 1} />
	{:else if isTableBlock(block)}
		<TableBlock {block} />
	{:else if isErrorBlock(block)}
		<ErrorBlock mensaje={block.mensaje} {onretry} />
	{/if}
{/each}
