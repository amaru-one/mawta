<script lang="ts">
	import { goto } from '$app/navigation';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
	import {
		APP_VERSION,
		PROFILE_ACTIVITY,
		PROFILE_CLASSES,
		PROFILE_STATS,
		TEACHER
	} from '$lib/mocks';
	import { showToast } from '$lib/toast';

	let showLogoutConfirm = $state(false);

	const totalClasses = PROFILE_CLASSES.reduce((sum, g) => sum + g.classes.length, 0);

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
	<div class="identity">
		<span class="avatar big">{TEACHER.initials}</span>
		<p class="name">{TEACHER.fullName}</p>
		<p class="line">{TEACHER.role}</p>
		<p class="line">{TEACHER.schoolFull}</p>
		<p class="meta since">{TEACHER.since}</p>
	</div>

	<div class="grid3 stats">
		{#each PROFILE_STATS as stat (stat.label)}
			<div class="stat centered">
				<p class="stat-value">{stat.value}</p>
				<p class="stat-label">{stat.label}</p>
			</div>
		{/each}
	</div>

	<p class="eyebrow">ACTIVIDAD · BIMESTRE II</p>
	<div class="card activity">
		{#each PROFILE_ACTIVITY as item, i (item.label)}
			{#if i > 0}<div class="divider"></div>{/if}
			<div class="row activity-row">
				<span class="activity-icon"><Icon name={item.icon} size={17} /></span>
				<span class="activity-label">{item.label}</span>
				<span class="activity-value" class:danger={item.danger}>{item.value}</span>
			</div>
		{/each}
	</div>

	<button class="btn-block logout pressable" onclick={() => (showLogoutConfirm = true)}>
		<Icon name="logout" size={16} />Cerrar sesión
	</button>

	<p class="eyebrow classes-head">MIS CLASES · {totalClasses}</p>

	{#each PROFILE_CLASSES as group (group.label)}
		<div class="row group-head">
			<p class="meta group-label">{group.label}</p>
			<div class="rule"></div>
			<span class="group-count">{group.classes.length}</span>
		</div>
		<div class="card group">
			{#each group.classes as klass, i (klass.name)}
				{#if i > 0}<div class="divider"></div>{/if}
				<div class="row class-row">
					<span class="class-name">{klass.name}</span>
					<span class="class-meta">{klass.students} · {klass.perWeek}/sem</span>
				</div>
			{/each}
		</div>
	{/each}

	<p class="meta version">{APP_VERSION}</p>
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

	.identity {
		display: flex;
		flex-direction: column;
		align-items: center;
		margin-bottom: 20px;
	}

	.avatar.big {
		width: 72px;
		height: 72px;
		font-size: 22px;
		margin-bottom: 10px;
	}

	.name {
		margin: 0;
		font-weight: 500;
		font-size: 18px;
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
		font-size: 19px;
		font-weight: 500;
	}

	.stat-label {
		margin: 2px 0 0;
		font-size: 11px;
		color: var(--text-secondary);
	}

	.activity {
		overflow: hidden;
		margin-bottom: var(--space-xl);
	}

	.activity-row {
		padding: 13px var(--space-lg);
	}

	.activity-icon {
		display: flex;
		color: var(--text-secondary);
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

	.logout {
		background: var(--surface-2);
		color: var(--text-danger);
		border: 0.5px solid var(--border-strong);
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
