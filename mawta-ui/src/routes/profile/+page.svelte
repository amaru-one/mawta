<script lang="ts">
	import { Button, Card, Icon, ListRow, LoadingState } from '$lib/design-system';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { list } from '$lib/api/client';
	import type { ProfileDto } from '$lib/api/dto';
	import { logout } from '$lib/api/endpoints/auth';
	import { getProfile } from '$lib/api/endpoints/profile';
	import { parseDateOnly } from '$lib/api/mappers';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import type { IconName } from '$lib/icons';
	import { hapticTap } from '$lib/haptics';
	import { session, teacher } from '$lib/stores';
	import { showToast } from '$lib/toast';

	const APP_VERSION = 'Mawta v1.0.4';

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
			.split(' ')
			.slice(0, 2)
			.map((w) => w[0] ?? '')
			.join('')
			.toUpperCase()
	);

	const school = $derived(
		profile ? `${profile.tenant_name}${profile.tenant_city ? ` · ${profile.tenant_city}` : ''}` : ''
	);

	const since = $derived.by(() => {
		if (!profile?.hired_on) return '';
		// Date-only column serialized as midnight UTC; parse without the shift.
		const hired = parseDateOnly(profile.hired_on.slice(0, 10));
		const label = hired.toLocaleDateString('es-PE', { month: 'long', year: 'numeric' });
		const years = Math.floor((Date.now() - hired.getTime()) / (365.25 * 24 * 3600 * 1000));
		return `Desde ${label}${years > 0 ? ` · ${years} ${years === 1 ? 'año' : 'años'}` : ''}`;
	});

	const stats = $derived(
		profile
			? [
					{ value: String(profile.top_stats.classes), label: 'Clases' },
					{ value: String(profile.top_stats.students), label: 'Alumnos' },
					{ value: `${Math.round(profile.top_stats.weekly_hours)}h`, label: 'Semanales' },
				]
			: []
	);

	type ActivityRow = { icon: IconName; label: string; value: string; danger?: boolean };
	const activity = $derived.by((): ActivityRow[] => {
		if (!profile) return [];
		const a = profile.activity;
		return [
			{ icon: 'presentation', label: 'Clases dictadas', value: String(a.clases_dictadas) },
			{
				icon: 'clipboard-check',
				label: 'Asistencias registradas',
				value: `${a.asistencias_registradas} / ${a.asistencias_esperadas}`,
			},
			{ icon: 'mic', label: 'Notas de voz', value: String(a.notas_de_voz) },
			{ icon: 'checklist', label: 'Evaluaciones registradas', value: String(a.evaluaciones) },
		];
	});

	const classGroups = $derived(list(profile?.classes_by_grade));
	const totalClasses = $derived(classGroups.reduce((sum, g) => sum + g.classes.length, 0));

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

<svelte:head>
	<title>Mi perfil</title>
</svelte:head>
<div class="view">
	<TopBar back="/" title="Mi perfil" showBell={false} />

	<div class="body top">
		{#if ready && profile}
			<div class="identity">
				<span class="mw-avatar big">{initials}</span>
				<p class="name">{profile.display_name}</p>
				{#if profile.title}<p class="line">{profile.title}</p>{/if}
				<p class="line">{school}</p>
				{#if since}<p class="meta since">{since}</p>{/if}
			</div>

			<div class="grid3 stats">
				{#each stats as stat (stat.label)}
					<div class="stat centered">
						<p class="stat-value">{stat.value}</p>
						<p class="stat-label">{stat.label}</p>
					</div>
				{/each}
			</div>

			<p class="eyebrow">ACTIVIDAD</p>
			<Card>
				{#each activity as item, i (item.label)}
					{#if i > 0}<div class="divider"></div>{/if}
					<div class="row activity-row">
						<span class="activity-icon"><Icon name={item.icon} size={17} /></span>
						<span class="activity-label">{item.label}</span>
						<span class="activity-value" class:danger={item.danger}>{item.value}</span>
					</div>
				{/each}
			</Card>

			<p class="eyebrow classes-head">MIS CLASES · {totalClasses}</p>

			{#each classGroups as group (group.grade_label)}
				<div class="row group-head">
					<p class="meta group-label">{group.grade_label}</p>
					<div class="rule"></div>
					<span class="group-count">{group.classes.length}</span>
				</div>
				<Card>
					{#each group.classes as klass, i (klass.class_id)}
						{#if i > 0}<div class="divider"></div>{/if}
						<!-- The only date-independent way into an área: Home is bounded to the
					     current ISO week, so a class whose sessions are all past is
					     unreachable from there. See this screen's SPEC. -->
						<ListRow href="/class/{klass.class_id}" onclick={hapticTap}>
							<span class="class-name grow">{klass.name}</span>
							<span class="class-meta">{klass.roster_count} · {klass.slots_per_week}/sem</span>
						</ListRow>
					{/each}
				</Card>
			{/each}

			<Button variant="secondary" block class="logout" onclick={() => (showLogoutConfirm = true)}>
				<Icon name="logout" size={16} />Cerrar sesión
			</Button>

			<p class="meta version">{APP_VERSION}</p>
		{:else if loadError}
			<p class="line">
				No se pudo cargar el perfil.
				<Button variant="secondary" onclick={load}>Reintentar</Button>
			</p>
		{:else}<LoadingState label="Cargando…" />{/if}
	</div>

	{#if showLogoutConfirm}
		<ConfirmDialog
			title="¿Cerrar sesión?"
			text="Tendrás que iniciar sesión de nuevo para acceder a tus clases."
			confirmLabel="Cerrar sesión"
			onconfirm={confirmLogout}
			oncancel={() => {
				hapticTap();
				showLogoutConfirm = false;
			}}
		/>
	{/if}
</div>

<style>
	.top {
		padding-top: 20px;
	}

	.identity {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding-bottom: 22px;

		margin-bottom: 20px;
	}

	.name {
		margin: 0;
		font-weight: 700;
		font-size: var(--mw-type-title-size);
		letter-spacing: -0.02em;
		line-height: 1.1;
		text-align: center;
	}

	.line {
		margin: var(--mw-space-1) 0 0;
		font-size: var(--mw-type-small-size);
		color: var(--mw-ink-secondary);
	}

	.line + .line {
		margin-top: 2px;
	}

	.since {
		margin: var(--mw-space-2) 0 0;
	}

	.stats {
		margin-bottom: 22px;
	}

	.centered {
		text-align: center;
	}

	.stat-value {
		margin: 0;
		font-size: var(--mw-type-title-size);
		font-weight: 800;
		letter-spacing: -0.02em;
		color: var(--mw-accent);
	}

	.stat-label {
		margin: 2px 0 0;
		font-family: var(--mw-font-sans);
		font-size: var(--mw-type-label-size);
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--mw-ink-muted);
	}

	.activity-row {
		padding: 13px var(--mw-space-4);
	}

	.activity-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 30px;
		height: 30px;
		border-radius: 9px;
		background: var(--mw-surface-tint);
		color: var(--mw-accent);
		flex-shrink: 0;
	}

	.activity-label {
		flex: 1;
		font-size: var(--mw-type-body-size);
	}

	.activity-value {
		font-size: var(--mw-type-body-size);
		font-weight: 500;
	}

	.activity-value.danger {
		color: var(--mw-danger);
	}
	.view :global(.logout) {
		margin-top: var(--mw-space-6);
		margin-bottom: var(--mw-space-6);
	}

	.classes-head {
		margin-bottom: var(--mw-space-3);
	}

	.group-head {
		gap: var(--mw-space-2);
		margin-bottom: var(--mw-space-2);
	}

	.group-label {
		margin: 0;
	}

	.rule {
		flex: 1;
		height: 0.5px;
		background: var(--mw-line);
	}

	.group-count {
		font-size: var(--mw-type-label-size);
		color: var(--mw-ink-muted);
	}

	.class-name {
		font-size: var(--mw-type-small-size);
	}

	.class-meta {
		font-size: var(--mw-type-label-size);
		color: var(--mw-ink-muted);
		flex-shrink: 0;
	}

	.version {
		margin: var(--mw-space-4) 0 0;
		text-align: center;
	}
</style>
