<script lang="ts">
	import type { Snippet } from 'svelte';
	let {
		children,
		actions,
		class: className = '',
	}: { children: Snippet; actions?: Snippet; class?: string } = $props();
</script>

<div class="mw-card {className}">
	<div class="mw-card__body">{@render children()}</div>
	{#if actions}<div class="mw-card__actions">{@render actions()}</div>{/if}
</div>
