<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { afterNavigate } from '$app/navigation';
	import favicon from '$lib/assets/favicon.svg';
	import IconSprite from '$lib/components/IconSprite.svelte';
	import Toast from '$lib/components/Toast.svelte';
	import { getMe } from '$lib/api/endpoints/home';
	import { loadNotifications } from '$lib/notifications';
	import { canGoBack, teacher } from '$lib/stores';

	let { children } = $props();

	// Any navigation other than the initial load leaves an entry behind us, so
	// an in-app `history.back()` is safe from then on. Screens reachable from
	// more than one place use this instead of a hardcoded back destination.
	// The test is on `type`, not on `from`: SvelteKit passes a non-null `from`
	// whose `url` is null for the `enter` navigation, so a truthiness check on
	// `from` alone is true on a cold load and sends the back arrow out of the app.
	afterNavigate((nav) => {
		if (nav.type !== 'enter') canGoBack.set(true);
	});

	onMount(() => {
		getMe()
			.then((me) => {
				const name = me.user.display_name;
				teacher.set({
					initials: name
						.split(' ')
						.slice(0, 2)
						.map((w) => w[0] ?? '')
						.join('')
						.toUpperCase(),
					shortName: name,
					school: me.tenant.name
				});
			})
			.catch(() => {});

		// The feed also drives the unread badge; a slow poll keeps both fresh.
		void loadNotifications().catch(() => {});
		const poll = setInterval(() => void loadNotifications().catch(() => {}), 60_000);
		return () => clearInterval(poll);
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
</svelte:head>

<IconSprite />

<div class="app-shell">
	{@render children()}
</div>

<Toast />
