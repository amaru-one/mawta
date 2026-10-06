<script lang="ts">
	import type { Snippet } from 'svelte';
	import IconButton from './IconButton.svelte';
	let {
		name = '',
		school = '',
		initials = '',
		title,
		backHref,
		identityHref,
		notificationsHref,
		onback,
		onnotifications,
		onidentity,
		notificationCount = 0,
		actions,
		status,
	}: {
		name?: string;
		school?: string;
		initials?: string;
		title?: string;
		backHref?: string;
		identityHref?: string;
		notificationsHref?: string;
		onback?: (event: MouseEvent) => void;
		onnotifications?: (event: MouseEvent) => void;
		onidentity?: (event: MouseEvent) => void;
		notificationCount?: number;
		actions?: Snippet;
		status?: Snippet;
	} = $props();
</script>

<header class="mw-topbar">
	{#if backHref || onback}<IconButton
			icon="arrow-left"
			label="Volver"
			href={backHref}
			onclick={onback}
		/>{/if}
	{#snippet identity()}<span class="mw-avatar" aria-hidden="true">{initials}</span><span
			class="mw-topbar__who"
			><span class="mw-topbar__name">{name}</span><span class="mw-meta">{school}</span></span
		>{/snippet}
	{#if title}<p class="mw-topbar__title">{title}</p>
	{:else if identityHref}<a
			class="mw-topbar__identity"
			href={identityHref}
			onclick={onidentity}
			aria-label="Mi perfil: {name}">{@render identity()}</a
		>
	{:else if onidentity}<button
			type="button"
			class="mw-topbar__identity"
			onclick={onidentity}
			aria-label="Mi perfil: {name}">{@render identity()}</button
		>
	{:else}<div class="mw-topbar__identity">{@render identity()}</div>{/if}
	{#if actions}{@render actions()}{/if}
	{#if status}{@render status()}
	{:else if notificationsHref || onnotifications}<span class="mw-topbar__bell"
			><IconButton
				icon="bell"
				label={notificationCount > 0
					? `Notificaciones, ${notificationCount} sin leer`
					: 'Notificaciones'}
				href={notificationsHref}
				onclick={onnotifications}
			/>{#if notificationCount > 0}<span class="mw-topbar__unread" aria-hidden="true"
				></span>{/if}</span
		>{/if}
</header>
