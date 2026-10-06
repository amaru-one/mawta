<script lang="ts">
	import { Action, Notice } from '$lib/design-system';
	import { page } from '$app/state';
	import TopBar from '$lib/components/TopBar.svelte';
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
	<Action href="/">Volver al inicio</Action>
</main>
