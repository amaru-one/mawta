<script lang="ts">
	import { Button, Field } from '$lib/design-system';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { safeNext } from '$lib/auth';
	import { ApiError } from '$lib/api/client';
	import { login } from '$lib/api/endpoints/auth';
	import { session, teacher } from '$lib/stores';

	let username = $state('');
	let password = $state('');
	let submitting = $state(false);
	let error = $state('');

	const canSubmit = $derived(username.trim() !== '' && password !== '' && !submitting);

	// Mirrors internal/httpapi/auth.go's error codes — see its SPEC.md.
	function messageFor(err: unknown): string {
		if (err instanceof ApiError) {
			switch (err.code) {
				case 'invalid_credentials':
					return 'Usuario o contraseña incorrectos.';
				case 'account_locked':
					return 'Demasiados intentos. Espera unos minutos e inténtalo de nuevo.';
				case 'role_not_enabled':
					return 'El acceso para tu rol aún no está disponible.';
				case 'no_membership':
					return 'Tu cuenta no está activa en ningún colegio.';
				case 'not_a_teacher_profile':
					return 'Tu cuenta no tiene un perfil docente en este colegio.';
			}
		}
		return 'No pudimos iniciar sesión. Revisa tu conexión.';
	}

	async function handleSubmit(e: Event): Promise<void> {
		e.preventDefault();
		if (!canSubmit) return;
		submitting = true;
		error = '';
		try {
			const me = await login(username.trim(), password);
			const name = me.user.display_name;
			teacher.set({
				initials: name
					.split(' ')
					.slice(0, 2)
					.map((w) => w[0] ?? '')
					.join('')
					.toUpperCase(),
				shortName: name,
				school: me.tenant.name,
			});
			session.set({ status: 'authenticated', role: me.role });
			await goto(safeNext(page.url.searchParams.get('next')) ?? '/', { replaceState: true });
		} catch (err) {
			error = messageFor(err);
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>Iniciar sesión</title>
</svelte:head>
<div class="view">
	<div class="body screen">
		<h1 class="screen-title">Iniciar sesión</h1>
		<p class="screen-sub">Ingresa con tu usuario del colegio</p>

		<form onsubmit={handleSubmit}>
			<Field
				label="Usuario"
				type="text"
				name="username"
				autocomplete="username"
				bind:value={username}
				disabled={submitting}
			/>

			<Field
				label="Contraseña"
				type="password"
				name="password"
				autocomplete="current-password"
				bind:value={password}
				disabled={submitting}
			/>

			{#if error}
				<p class="error" role="alert">{error}</p>
			{/if}

			<Button variant="primary" block type="submit" disabled={!canSubmit}>
				{submitting ? 'Ingresando…' : 'Ingresar'}
			</Button>
		</form>
	</div>
</div>

<style>
	.screen {
		display: flex;
		flex-direction: column;
		justify-content: center;
		min-height: 100vh;
		max-width: var(--mw-shell-width);
		margin: 0 auto;
	}

	form {
		display: flex;
		flex-direction: column;
		gap: var(--mw-space-4);
		margin-top: var(--mw-space-6);
	}

	.error {
		margin: 0;
		font-size: var(--mw-type-small-size);
		color: var(--mw-danger);
	}
</style>
