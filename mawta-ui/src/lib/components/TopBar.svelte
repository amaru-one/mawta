<script lang="ts">
	import { hapticTap } from '$lib/haptics';
	import { canGoBack, teacher, unreadNotificationCount } from '$lib/stores';
	import Icon from './Icon.svelte';

	interface Props {
		/**
		 * Destination for the back arrow; omitted on the Home view. With
		 * `useHistory` it is the fallback, used only when there is no in-app
		 * history to return to.
		 */
		back?: string;
		/**
		 * Go to the previous screen rather than to `back`. For screens reached
		 * from more than one place, where a fixed destination is wrong for
		 * every caller but one.
		 */
		useHistory?: boolean;
		/** Plain title instead of the teacher identity block (Profile view). */
		title?: string;
		/** Home shows a larger avatar and a logout shortcut. */
		variant?: 'default' | 'home';
		showBell?: boolean;
		/**
		 * A recording is in progress: the bell is replaced by a blinking marker.
		 * It takes the bell's slot rather than being layered over the bar by the
		 * screen, so nothing has to absolutely position over another component.
		 */
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

	const large = $derived(variant === 'home');
	const who = $derived($teacher ?? { initials: '', shortName: '', school: '' });
</script>

<div class="topbar">
	{#if back}
		<a class="nav pressable" href={back} onclick={onBack} aria-label="Volver">
			<Icon name="arrow-left" size={20} />
		</a>
	{/if}

	{#if title}
		<p class="plain-title">{title}</p>
	{:else}
		<a class="identity pressable" href="/profile" onclick={hapticTap}>
			<span class="avatar" class:large>{who.initials}</span>
			<span class="who">
				<span class="name" class:large>{who.shortName}</span>
				<span class="school" class:large>{who.school}</span>
			</span>
		</a>
	{/if}

	<!-- Shortcut out of any screen but Home itself. Hidden while a recording runs
	     for the same reason the bell cedes its slot to the REC marker: leaving the
	     lesson screen mid-hold would lose the note. -->
	{#if !recording && variant !== 'home'}
		<a class="nav pressable" href="/" onclick={hapticTap} aria-label="Ir al inicio">
			<Icon name="home" size={20} />
		</a>
	{/if}

	{#if recording}
		<span class="rec" role="status" aria-label="Grabando">
			<span class="rec-dot"></span>
			<span class="rec-label">REC</span>
		</span>
	{:else if showBell}
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
	/* A 40px target, not a 32px glyph with a negative margin: the bar is the
	   chrome every screen wears and its controls are the smallest things in the
	   app anyone taps. */
	.nav {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 40px;
		height: 40px;
		border-radius: 50%;
		color: var(--text-secondary);
		text-decoration: none;
		flex-shrink: 0;
	}

	.identity {
		display: flex;
		align-items: center;
		gap: 10px;
		flex: 1;
		min-width: 0;
		padding-left: 2px;
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

	/* Secondary, not primary: over --surface-1 the saturated ink only reaches
	   4.4:1, under AA for text this size. */
	.name {
		font-weight: 600;
		font-size: 15px;
		line-height: 1.3;
		color: var(--text-secondary);
	}

	.name.large {
		font-size: 16px;
	}

	.school {
		font-size: 12px;
		line-height: 1.3;
		color: var(--text-muted);
	}

	.school.large {
		font-size: 13px;
	}

	.plain-title {
		flex: 1;
		margin: 0;
		font-weight: 600;
		font-size: 16px;
		color: var(--text-secondary);
	}

	.bell {
		position: relative;
	}

	/* Takes the bell's slot while a recording is running. */
	.rec {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
	}

	.rec-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--fill-accent);
		animation: rec-blink 700ms ease-in-out infinite;
	}

	.rec-label {
		font-family: var(--font-mono);
		font-size: 10px;
		letter-spacing: 0.08em;
	}

	@keyframes rec-blink {
		0%,
		100% {
			opacity: 0.5;
		}
		50% {
			opacity: 1;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.rec-dot {
			animation: none;
		}
	}

	/* The unread marker is an assistant signal, hence the accent. The ring in
	   the bar's own colour is what keeps it readable now that the ink beside it
	   is the same family of indigo. */
	.unread {
		position: absolute;
		top: 7px;
		right: 7px;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--fill-accent);
		border: 2px solid var(--surface-1);
	}
</style>
