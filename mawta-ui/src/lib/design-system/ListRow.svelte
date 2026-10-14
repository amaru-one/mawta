<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	// A row of a list. With an href it is a link to another view (chevron shown);
	// without one it only shows information.
	let {
		href,
		children,
		trailing,
		onclick,
		label,
		class: className = '',
	}: {
		href?: string;
		children: Snippet;
		trailing?: Snippet;
		onclick?: (event: MouseEvent) => void;
		label?: string;
		class?: string;
	} = $props();
</script>

{#if href !== undefined}
	<a class="mw-list-row {className}" {href} {onclick} aria-label={label}
		><span class="mw-list-row__body">{@render children()}</span
		>{#if trailing}{@render trailing()}{/if}<Icon name="chevron-right" /></a
	>
{:else}
	<div class="mw-list-row mw-list-row--static {className}">
		<span class="mw-list-row__body">{@render children()}</span
		>{#if trailing}{@render trailing()}{/if}
	</div>
{/if}
