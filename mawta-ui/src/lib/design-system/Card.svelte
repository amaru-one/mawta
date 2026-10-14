<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	// A card is information. With onclick it opens another view: it becomes a
	// button-role element (block content, so not a <button>) with the chevron
	// every other navigating row shows, and Enter or Space activates it.
	let {
		children,
		actions,
		onclick,
		class: className = '',
	}: {
		children: Snippet;
		actions?: Snippet;
		onclick?: (event: MouseEvent) => void;
		class?: string;
	} = $props();

	function keyActivate(event: KeyboardEvent): void {
		if (event.key !== 'Enter' && event.key !== ' ') return;
		event.preventDefault();
		(event.currentTarget as HTMLElement).click();
	}
</script>

{#if onclick}
	<div
		class="mw-card mw-card--action {className}"
		role="button"
		tabindex="0"
		{onclick}
		onkeydown={keyActivate}
	>
		<div class="mw-card__body">{@render children()}</div>
		<span class="mw-card__chev" aria-hidden="true"><Icon name="chevron-right" size={16} /></span>
	</div>
{:else}
	<div class="mw-card {className}">
		<div class="mw-card__body">{@render children()}</div>
		{#if actions}<div class="mw-card__actions">{@render actions()}</div>{/if}
	</div>
{/if}
