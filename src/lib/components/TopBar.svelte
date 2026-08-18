<script lang="ts">
	import { hapticTap } from '$lib/haptics';
	import { TEACHER } from '$lib/mocks';
	import { unreadNotificationCount } from '$lib/stores';
	import Icon from './Icon.svelte';

	interface Props {
		/** Destination for the back arrow; omitted on the Home view. */
		back?: string;
		/** Plain title instead of the teacher identity block (Profile view). */
		title?: string;
		/** Home shows a larger avatar and a logout shortcut. */
		variant?: 'default' | 'home';
		showBell?: boolean;
	}

	let { back, title, variant = 'default', showBell = true }: Props = $props();

	const large = $derived(variant === 'home');
</script>

<div class="topbar">
	{#if back}
		<a class="nav pressable" href={back} onclick={hapticTap} aria-label="Volver">
			<Icon name="arrow-left" size={20} />
		</a>
	{/if}

	{#if title}
		<p class="plain-title">{title}</p>
	{:else}
		<a class="identity pressable" href="/profile" onclick={hapticTap}>
			<span class="avatar" class:large>{TEACHER.initials}</span>
			<span class="who">
				<span class="name" class:large>{TEACHER.shortName}</span>
				<span class="school" class:large>{TEACHER.school}</span>
			</span>
		</a>
	{/if}

	{#if showBell}
		<a
			class="nav bell pressable"
			href="/notifications"
			onclick={hapticTap}
			aria-label={$unreadNotificationCount > 0
				? `Notificaciones, ${$unreadNotificationCount} sin leer`
				: 'Notificaciones'}
		>
			<Icon name="bell" size={20} />
			{#if $unreadNotificationCount > 0}
				<span class="unread"></span>
			{/if}
		</a>
	{/if}

	{#if variant === 'home'}
		<a class="nav pressable" href="/profile" onclick={hapticTap} aria-label="Mi perfil">
			<Icon name="logout" size={20} />
		</a>
	{/if}
</div>

<style>
	.nav {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		margin: -6px;
		color: var(--text-primary);
		text-decoration: none;
		flex-shrink: 0;
	}

	.identity {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		flex: 1;
		min-width: 0;
		color: inherit;
		text-decoration: none;
	}

	.avatar.large {
		width: 44px;
		height: 44px;
		font-size: 14px;
	}

	.who {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.name {
		font-weight: 500;
		font-size: 15px;
		line-height: 1.3;
	}

	.name.large {
		font-size: 16px;
	}

	.school {
		font-size: 12px;
		line-height: 1.3;
		color: var(--text-secondary);
	}

	.school.large {
		font-size: 13px;
	}

	.plain-title {
		flex: 1;
		margin: 0;
		font-weight: 500;
		font-size: 15px;
	}

	.bell {
		position: relative;
	}

	/* The unread marker is an assistant signal, hence the accent. */
	.unread {
		position: absolute;
		top: 4px;
		right: 4px;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--fill-accent);
	}
</style>
