<script lang="ts">
	import { Button } from '$lib/design-system';
	import { goto } from '$app/navigation';
	import { logout } from '$lib/api/endpoints/auth';
	import { session, teacher } from '$lib/stores';

	// Placeholder until the director chat exists.
	async function handleLogout(): Promise<void> {
		try {
			await logout();
		} catch {
			// handleLogout is idempotent and clears the cookie either way.
		}
		session.set({ status: 'anonymous' });
		teacher.set(null);
		await goto('/login', { replaceState: true });
	}
</script>

<svelte:head>
	<title>Dirección</title>
</svelte:head>
<div class="view">
	<div class="body screen">
		<h1 class="screen-title">Hola, {$teacher?.shortName ?? ''}</h1>
		<p class="screen-sub">{$teacher?.school ?? ''}</p>
		<p>El chat de dirección estará disponible pronto.</p>
		<Button variant="secondary" block icon="logout" onclick={handleLogout}>Cerrar sesión</Button>
	</div>
</div>

<style>
	.screen {
		display: flex;
		flex-direction: column;
		gap: var(--mw-space-4);
		max-width: var(--mw-shell-width);
		margin: 0 auto;
	}
</style>
