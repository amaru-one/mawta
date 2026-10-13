<script lang="ts">
	import { Action, Button, Notice } from '$lib/design-system';
	import { invalidateAll } from '$app/navigation';
	import { page } from '$app/state';
	import TopBar from '$lib/components/TopBar.svelte';

	let retrying = $state(false);

	// A server failure may be gone a moment later, so offer to load this page again.
	async function retry(): Promise<void> {
		retrying = true;
		try {
			await invalidateAll();
		} finally {
			retrying = false;
		}
	}
</script>

<svelte:head><title>Página no disponible — Mawta</title></svelte:head>
<TopBar back="/" title="Mawta" />
<main class="body">
	<Notice variant="attention"
		><h1 class="screen-title">
			{page.status === 404 ? 'No encontramos esta página' : 'No pudimos abrir esta página'}
		</h1>
		<p>Vuelve al inicio para continuar con tus clases.</p></Notice
	>
	{#if page.status !== 404}
		<Button variant="secondary" block loading={retrying} onclick={retry}>Reintentar</Button>
	{/if}
	<Action href="/">Volver al inicio</Action>
</main>
