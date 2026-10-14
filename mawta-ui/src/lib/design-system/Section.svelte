<script lang="ts">
	import type { Snippet } from 'svelte';
	// A titled group of a screen. The title uses the same label style as the
	// eyebrows of every other screen; sections are spaced by the design system.
	let { title, children }: { title: string; children: Snippet } = $props();
</script>

<section class="mw-section">
	<h2 class="mw-section__title">{title}</h2>
	{@render children()}
</section>
