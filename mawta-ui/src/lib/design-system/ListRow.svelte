<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	let {
		href,
		children,
		trailing,
		onclick,
		label,
		class: className = '',
	}: {
		href: string;
		children: Snippet;
		trailing?: Snippet;
		onclick?: (event: MouseEvent) => void;
		label?: string;
		class?: string;
	} = $props();
</script>

<a class="mw-list-row {className}" {href} {onclick} aria-label={label}
	><span class="mw-list-row__body">{@render children()}</span
	>{#if trailing}{@render trailing()}{/if}<Icon name="chevron-right" /></a
>
