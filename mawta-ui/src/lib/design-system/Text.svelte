<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { TextVariant } from './types';
	let {
		children,
		variant = 'body',
		as = 'p',
		id,
		class: className = '',
	}: {
		children: Snippet;
		variant?: TextVariant;
		as?: 'p' | 'span' | 'h1' | 'h2' | 'h3' | 'h4';
		id?: string;
		class?: string;
	} = $props();
</script>

<svelte:element this={as} {id} class="mw-text mw-text--{variant} {className}"
	>{@render children()}</svelte:element
>
