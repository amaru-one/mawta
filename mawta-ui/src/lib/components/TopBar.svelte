<script lang="ts">
	import { IconButton, TopBar as NitidoTopBar } from '$lib/design-system';
	import { hapticTap } from '$lib/haptics';
	import { teacher, unreadNotificationCount } from '$lib/stores';

	interface Props {
		back?: string;

		title?: string;

		variant?: 'default' | 'home';
		showBell?: boolean;

		recording?: boolean;
	}

	let { back, title, variant = 'default', showBell = true, recording = false }: Props = $props();

	// "Volver" always climbs to the fixed parent in the navigation tree; the
	// href does the navigation, so there is nothing to pop from history.
	function onBack(): void {
		hapticTap();
	}

	const who = $derived($teacher ?? { initials: '', shortName: '', school: '' });
</script>

{#snippet recordingStatus()}<span class="record-status" role="status">● Grabando</span>{/snippet}
<NitidoTopBar
	name={who.shortName}
	school={who.school}
	initials={who.initials}
	{title}
	backHref={recording ? undefined : back}
	onback={recording || !back ? undefined : onBack}
	identityHref={recording ? undefined : '/profile'}
	onidentity={recording ? undefined : hapticTap}
	notificationsHref={!recording && showBell ? '/notifications' : undefined}
	onnotifications={!recording && showBell ? hapticTap : undefined}
	notificationCount={$unreadNotificationCount}
	status={recording ? recordingStatus : undefined}
>
	{#snippet actions()}{#if !recording && variant !== 'home' && back && back !== '/'}<IconButton
				icon="home"
				label="Ir al inicio"
				href="/"
				onclick={hapticTap}
			/>{/if}{/snippet}
</NitidoTopBar>

<style>
	.record-status {
		color: var(--mw-accent);
		font-size: var(--mw-type-label-size);
		font-weight: 700;
	}
</style>
