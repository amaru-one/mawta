<script lang="ts">
	import { IconButton, TopBar as NitidoTopBar } from '$lib/design-system';
	import { hapticTap } from '$lib/haptics';
	import { canGoBack, teacher, unreadNotificationCount } from '$lib/stores';

	interface Props {
		back?: string;

		useHistory?: boolean;

		title?: string;

		variant?: 'default' | 'home';
		showBell?: boolean;

		recording?: boolean;
	}

	let {
		back,
		useHistory = false,
		title,
		variant = 'default',
		showBell = true,
		recording = false,
	}: Props = $props();

	function onBack(event: MouseEvent): void {
		hapticTap();
		// Nothing to pop (cold load, refresh, deep link): let the href stand.
		if (!useHistory || !$canGoBack) return;
		// Modified clicks mean "open the fallback elsewhere" — don't hijack them.
		if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
		event.preventDefault();
		history.back();
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
	{#snippet actions()}{#if !recording && variant !== 'home'}<IconButton
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
