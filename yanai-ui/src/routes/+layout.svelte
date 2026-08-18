<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import favicon from '$lib/assets/favicon.svg';
	import IconSprite from '$lib/components/IconSprite.svelte';
	import Toast from '$lib/components/Toast.svelte';
	import { loadMockNotifications } from '$lib/notifications';

	let { children } = $props();

	onMount(() => {
		loadMockNotifications();
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
</svelte:head>

<IconSprite />

<div class="app-shell">
	{@render children()}
</div>

<Toast />
