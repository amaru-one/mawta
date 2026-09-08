<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { list } from '$lib/api/client';
	import type { ProfileDto } from '$lib/api/dto';
	import { getProfile } from '$lib/api/endpoints/profile';
	import { parseDateOnly } from '$lib/api/mappers';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import type { IconName } from '$lib/icons';
	import { hapticTap } from '$lib/haptics';
	import { showToast } from '$lib/toast';

	const APP_VERSION = 'Yanai v1.0.4';

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

	// UI-only for now — no auth/session backend exists yet to actually log out of.
	function confirmLogout(): void {
		showLogoutConfirm = false;
		showToast('Sesión cerrada');
		void goto('/');
	}
</script>

<svelte:head>
	<title>Mi perfil</title>
</svelte:head>

<TopBar back="/" title="Mi perfil" showBell={false} />

<div class="body top">
	{#if ready && profile}
		<div class="identity">
			<span class="avatar big">{initials}</span>
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
		<div class="card activity">
			{#each activity as item, i (item.label)}
				{#if i > 0}<div class="divider"></div>{/if}
				<div class="row activity-row">
					<span class="activity-icon"><Icon name={item.icon} size={17} /></span>
					<span class="activity-label">{item.label}</span>
					<span class="activity-value" class:danger={item.danger}>{item.value}</span>
				</div>
			{/each}
		</div>

		<p class="eyebrow classes-head">MIS CLASES · {totalClasses}</p>

		{#each classGroups as group (group.grade_label)}
			<div class="row group-head">
				<p class="meta group-label">{group.grade_label}</p>
				<div class="rule"></div>
				<span class="group-count">{group.classes.length}</span>
			</div>
			<div class="card group">
				{#each group.classes as klass, i (klass.class_id)}
					{#if i > 0}<div class="divider"></div>{/if}
					<div class="row class-row">
						<span class="class-name">{klass.name}</span>
						<span class="class-meta">{klass.roster_count} · {klass.slots_per_week}/sem</span>
					</div>
				{/each}
			</div>
		{/each}

		<button class="btn-block logout pressable" onclick={() => (showLogoutConfirm = true)}>
			<Icon name="logout" size={16} />Cerrar sesión
		</button>

		<p class="meta version">{APP_VERSION}</p>
	{:else if loadError}
		<p class="line">
			No se pudo cargar el perfil.
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
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

<style>
	.top {
		padding-top: 20px;
	}

	/* The identity block IS this screen's title, so it carries the same 34px and
	   the same rule under it as every other screen's h1. */
	.identity {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding-bottom: 22px;
		border-bottom: 1.5px solid var(--text-primary);
		margin-bottom: 20px;
	}

	.avatar.big {
		width: 76px;
		height: 76px;
		font-size: 26px;
		font-weight: 800;
		margin-bottom: 8px;
		background: var(--gradient-tile);
		border: none;
		color: var(--on-primary);
		box-shadow: 0 12px 26px rgba(74, 95, 214, 0.26);
	}

	.name {
		margin: 0;
		font-weight: 700;
		font-size: 34px;
		letter-spacing: -0.02em;
		line-height: 1.1;
		text-align: center;
	}

	.line {
		margin: var(--space-xs) 0 0;
		font-size: 13px;
		color: var(--text-secondary);
	}

	.line + .line {
		margin-top: 2px;
	}

	.since {
		margin: var(--space-sm) 0 0;
	}

	.stats {
		margin-bottom: 22px;
	}

	.centered {
		text-align: center;
	}

	.stat-value {
		margin: 0;
		font-size: 24px;
		font-weight: 800;
		letter-spacing: -0.02em;
		color: var(--aurora-deep);
	}

	.stat-label {
		margin: 2px 0 0;
		font-family: var(--font-mono);
		font-size: 10px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	.activity {
		overflow: hidden;
		margin-bottom: var(--space-xl);
	}

	.activity-row {
		padding: 13px var(--space-lg);
	}

	/* A tinted tile, so the four activity rows read as one group rather than as
	   four loose glyphs. */
	.activity-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 30px;
		height: 30px;
		border-radius: 9px;
		background: var(--aurora-tint);
		color: var(--aurora-deep);
		flex-shrink: 0;
	}

	.activity-label {
		flex: 1;
		font-size: 14px;
	}

	.activity-value {
		font-size: 14px;
		font-weight: 500;
	}

	.activity-value.danger {
		color: var(--text-danger);
	}

	/* Not the primary action of the screen, and deliberately not tinted with the
	   aurora either: it is the one thing here you should not reach for by
	   accident. */
	.logout {
		background: var(--surface-1);
		color: var(--text-secondary);
		margin-top: var(--space-xl);
		margin-bottom: var(--space-xl);
	}

	.classes-head {
		margin-bottom: var(--space-md);
	}

	.group-head {
		gap: var(--space-sm);
		margin-bottom: var(--space-sm);
	}

	.group-label {
		margin: 0;
	}

	.rule {
		flex: 1;
		height: 0.5px;
		background: var(--border);
	}

	.group-count {
		font-size: 11px;
		color: var(--text-muted);
	}

	.group {
		border-radius: var(--radius);
		overflow: hidden;
		margin-bottom: 14px;
	}

	.class-row {
		padding: 10px 14px;
	}

	.class-name {
		flex: 1;
		font-size: 13px;
	}

	.class-meta {
		font-size: 11px;
		color: var(--text-muted);
	}

	.version {
		margin: var(--space-lg) 0 0;
		text-align: center;
	}
</style>
