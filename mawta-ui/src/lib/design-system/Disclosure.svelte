<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	let {
		open = $bindable(false),
		summary,
		children,
		ontoggle,
	}: {
		open?: boolean;
		summary: Snippet;
		children: Snippet;
		ontoggle?: (open: boolean) => void;
	} = $props();
	const uid = $props.id();
</script>

<section class="mw-disclosure">
	<button
		type="button"
		class="mw-disclosure__toggle"
		aria-expanded={open}
		aria-controls={uid}
		onclick={() => {
			open = !open;
			ontoggle?.(open);
		}}><span>{@render summary()}</span><Icon name={open ? 'chevron-up' : 'chevron-down'} /></button
	>
	<div id={uid} hidden={!open} class="mw-disclosure__body">{@render children()}</div>
</section>
