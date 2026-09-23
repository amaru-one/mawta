<script lang="ts">
	import { goto } from '$app/navigation';
	import { ApiError } from '$lib/api/client';
	import { login } from '$lib/api/endpoints/auth';
	import { session, teacher, usesInternalGrading } from '$lib/stores';

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
			usesInternalGrading.set(me.tenant.uses_internal_grading);
			session.set({ status: 'authenticated', role: me.role });
			await goto('/', { replaceState: true });
		} catch (err) {
			error = messageFor(err);
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>Iniciar sesión</title>
</svelte:head>

<div class="body screen">
	<h1 class="screen-title">Iniciar sesión</h1>
	<p class="screen-sub">Ingresa con tu usuario del colegio</p>

	<form onsubmit={handleSubmit}>
		<label class="field">
			<span>Usuario</span>
			<input
				type="text"
				name="username"
				autocomplete="username"
				bind:value={username}
				disabled={submitting}
			/>
		</label>

		<label class="field">
			<span>Contraseña</span>
			<input
				type="password"
				name="password"
				autocomplete="current-password"
				bind:value={password}
				disabled={submitting}
			/>
		</label>

		{#if error}
			<p class="error" role="alert">{error}</p>
		{/if}

		<button type="submit" class="btn-block btn-primary pressable" disabled={!canSubmit}>
			{submitting ? 'Ingresando…' : 'Ingresar'}
		</button>
	</form>
</div>

<style>
	.screen {
		display: flex;
		flex-direction: column;
		justify-content: center;
		min-height: 100vh;
		max-width: var(--shell-width);
		margin: 0 auto;
	}

	form {
		display: flex;
		flex-direction: column;
		gap: var(--space-lg);
		margin-top: var(--space-xl);
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-size: 12px;
		color: var(--text-secondary);
	}

	.field input {
		font-size: 16px;
		color: var(--text-primary);
		background: var(--surface-1);
		border: 0.5px solid var(--border);
		border-radius: var(--radius-sm);
		padding: 12px 14px;
		font-family: inherit;
	}

	.field input:focus {
		outline: none;
		border-color: var(--border-strong);
	}

	.error {
		margin: 0;
		font-size: 13px;
		color: var(--text-danger);
	}

	.btn-block:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
