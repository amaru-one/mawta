<script lang="ts">
	import type { Snippet } from 'svelte';
	import IconButton from './IconButton.svelte';
	let {
		name,
		school,
		initials,
		onback,
		onnotifications,
		onidentity,
		notificationCount = 0,
		actions,
	}: {
		name: string;
		school: string;
		initials: string;
		onback?: () => void;
		onnotifications?: () => void;
		onidentity?: () => void;
		notificationCount?: number;
		actions?: Snippet;
	} = $props();
</script>

<header class="mw-topbar">
	{#if onback}<IconButton icon="arrow-left" label="Volver" onclick={onback} />{/if}
	{#snippet identity()}<span class="mw-avatar" aria-hidden="true">{initials}</span><span
			class="mw-topbar__who"
			><span class="mw-topbar__name">{name}</span><span class="mw-meta">{school}</span></span
		>{/snippet}
	{#if onidentity}<button
			type="button"
			class="mw-topbar__identity"
			onclick={onidentity}
			aria-label="Mi perfil: {name}">{@render identity()}</button
		>{:else}<div class="mw-topbar__identity">{@render identity()}</div>{/if}
	{#if onnotifications}<span class="mw-topbar__bell"
			><IconButton
				icon="bell"
				label={notificationCount > 0
					? `Notificaciones, ${notificationCount} sin leer`
					: 'Notificaciones'}
				onclick={onnotifications}
			/>{#if notificationCount > 0}<span class="mw-topbar__unread" aria-hidden="true"
				></span>{/if}</span
		>{/if}
	{#if actions}{@render actions()}{/if}
</header>
