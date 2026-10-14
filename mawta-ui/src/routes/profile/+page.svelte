<script lang="ts">
	import {
		Button,
		ConfirmDialog,
		Context,
		ErrorNotice,
		Icon,
		LoadingState,
		Notice,
		TopBar,
	} from '$lib/design-system';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { list } from '$lib/api/client';
	import type { ProfileDto } from '$lib/api/dto';
	import { logout } from '$lib/api/endpoints/auth';
	import { getProfile } from '$lib/api/endpoints/profile';
	import { hapticTap } from '$lib/haptics';
	import { session, teacher } from '$lib/stores';
	import { showToast } from '$lib/toast';

	let showLogoutConfirm = $state(false);
	let ready = $state(false);
	let loadError = $state(false);
	let profile = $state<ProfileDto | null>(null);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			profile = await getProfile();
			ready = true;
		} catch {
			loadError = true;
		}
	}

	onMount(load);

	const initials = $derived(
		(profile?.display_name ?? '')
			.trim()
			.split(/\s+/)
			.slice(0, 2)
			.map((w) => w[0] ?? '')
			.join('')
			.toUpperCase()
	);

	const classGroups = $derived(list(profile?.classes_by_grade));
	const assignments = $derived(
		classGroups.flatMap((group) =>
			list(group.classes).map((klass) => ({ ...klass, grade: group.grade_label }))
		)
	);
	const grades = $derived([...new Set(classGroups.map((group) => group.grade_label))]);

	async function confirmLogout(): Promise<void> {
		showLogoutConfirm = false;
		try {
			await logout();
		} catch {
			// The cookie is cleared server-side either way (handleLogout is
			// idempotent); proceed to the login screen regardless.
		}
		session.set({ status: 'anonymous' });
		teacher.set(null);
		showToast('Sesión cerrada');
		await goto('/login', { replaceState: true });
	}
</script>

<svelte:head><title>Mi perfil</title></svelte:head>
<div class="profile-page">
	<TopBar title="Mi perfil" backHref="/" onback={hapticTap}>
		{#snippet actions()}<span class="brand">mawta</span>{/snippet}
	</TopBar>
	<main class="profile-content">
		{#if ready && profile}
			<section class="identity" aria-label="Identidad del docente">
				<span class="avatar" aria-hidden="true">{initials}</span>
				<h1 class="screen-title">{profile.display_name}</h1>
				<p class="role">{profile.title || 'Docente'}</p>
			</section>
			<section class="profile-section" aria-labelledby="school-title">
				<h2 id="school-title">Mi colegio</h2>
				<Context class="school-card">
					<div class="school">
						<Icon name="bank" />
						<div>
							<p class="school-name">{profile.tenant_name}</p>
							{#if profile.tenant_city}<p class="school-city">{profile.tenant_city}</p>{/if}
						</div>
					</div>
				</Context>
			</section>
			{#if assignments.length > 0}
				<section class="profile-section" aria-labelledby="teaching-title">
					<h2 id="teaching-title">Mi enseñanza</h2>
					<dl class="details">
						<div class="detail">
							<dt>Asignaturas</dt>
							<dd>
								{#each assignments as assignment (assignment.class_id)}
									<a
										href="/class/{assignment.class_id}"
										onclick={hapticTap}
										aria-label="{assignment.name} · {assignment.grade}"
									>
										{assignment.name}
										{#if assignments.filter((item) => item.name === assignment.name).length > 1}
											<span class="assignment-grade">{assignment.grade}</span>
										{/if}
										<Icon name="chevron-right" size={16} /></a
									>
								{/each}
							</dd>
						</div>
						<div class="detail">
							<dt>Grados</dt>
							<dd>
								{#each grades as grade (grade)}<span>{grade}</span>{/each}
							</dd>
						</div>
					</dl>
				</section>
			{/if}
		{:else if loadError}
			<ErrorNotice message="No se pudo cargar el perfil." onretry={load} />
		{:else}<LoadingState label="Cargando perfil…" />{/if}
	</main>
	{#if ready && profile}
		<footer class="account">
			<Button variant="secondary" block icon="logout" onclick={() => (showLogoutConfirm = true)}
				>Cerrar sesión</Button
			>
		</footer>
	{/if}
	{#if showLogoutConfirm}
		<ConfirmDialog
			open
			title="¿Cerrar sesión?"
			description="Tendrás que iniciar sesión de nuevo para acceder a tus clases."
			confirmLabel="Cerrar sesión"
			tone="danger"
			onconfirm={confirmLogout}
			oncancel={() => {
				hapticTap();
				showLogoutConfirm = false;
			}}
		/>
	{/if}
</div>

<style>
	.profile-page {
		display: flex;
		flex-direction: column;
		min-height: 100dvh;
	}
	.brand {
		margin-left: auto;
		font-size: var(--mw-type-small-size);
		font-weight: 800;
		letter-spacing: -0.03em;
		color: var(--mw-accent);
	}
	.profile-content {
		padding: 40px var(--mw-space-5) var(--mw-space-8);
		flex: 1;
	}
	.identity {
		text-align: center;
		padding-bottom: 40px;
	}
	.avatar {
		display: grid;
		place-items: center;
		width: 88px;
		height: 88px;
		margin: 0 auto var(--mw-space-5);
		border-radius: var(--mw-radius-full);
		background: var(--mw-surface-tint);
		color: var(--mw-accent);
		font-size: 28px;
		font-weight: 800;
	}
	h1 {
		margin: 0;
		font-size: var(--mw-type-display-size);
		line-height: 38px;
		letter-spacing: -0.04em;
		font-weight: 800;
	}
	.role {
		margin: var(--mw-space-2) 0 0;
		color: var(--mw-ink-muted);
		line-height: 24px;
	}
	.profile-section {
		margin-bottom: var(--mw-space-8);
	}
	h2 {
		margin: 0 0 var(--mw-space-3);
		font-size: var(--mw-type-label-size);
		line-height: 16px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--mw-ink-muted);
	}
	.profile-page :global(.school-card) {
		padding: var(--mw-space-5);
	}
	.school {
		display: flex;
		align-items: flex-start;
		gap: var(--mw-space-3);
	}
	.school > :global(.mw-icon) {
		color: var(--mw-accent);
		margin-top: 2px;
	}
	.school-name {
		margin: 0;
		font-size: 16px;
		line-height: 24px;
		font-weight: 700;
	}
	.school-city {
		margin: var(--mw-space-1) 0 0;
		font-size: var(--mw-type-small-size);
		line-height: 20px;
		color: var(--mw-ink-secondary);
	}
	.details {
		margin: 0;
		border-top: 1px solid var(--mw-line);
	}
	.detail {
		padding: var(--mw-space-5) 0;
		display: grid;
		grid-template-columns: 96px minmax(0, 1fr);
		gap: var(--mw-space-4);
		border-bottom: 1px solid var(--mw-line);
		line-height: 24px;
	}
	dt {
		color: var(--mw-ink-muted);
	}
	dd {
		margin: 0;
		font-weight: 600;
	}
	dd > span,
	dd > a {
		display: block;
	}
	dd > a {
		padding: var(--mw-space-2) 0;
		display: flex;
		align-items: center;
		min-height: var(--mw-touch-target);
	}
	dd > a:first-child {
		margin-top: calc(-1 * var(--mw-space-2));
	}
	dd > a:last-child {
		margin-bottom: calc(-1 * var(--mw-space-2));
	}
	dd > a:hover {
		color: var(--mw-accent);
		text-decoration: underline;
	}
	.assignment-grade {
		display: block;
		font-size: var(--mw-type-small-size);
		font-weight: 400;
		color: var(--mw-ink-muted);
	}
	.account {
		margin-top: auto;
		padding: 0 var(--mw-space-5) var(--mw-space-6);
	}
	@media (max-width: 350px) {
		h1 {
			font-size: 26px;
		}
		.detail {
			grid-template-columns: 80px minmax(0, 1fr);
			gap: var(--mw-space-3);
		}
	}
</style>
