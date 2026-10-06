<script lang="ts">
	import './styles.css';
	import type { ContentProps } from './types';
	let { children, class: className = '' }: ContentProps = $props();
</script>

<svelte:head>
	<link
		rel="stylesheet"
		href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400..800&amp;display=swap"
	/>
</svelte:head>
<div class="mw-root {className}" data-mw-theme="indigo">{@render children()}</div>
