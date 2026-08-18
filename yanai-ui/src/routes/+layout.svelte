<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import favicon from '$lib/assets/favicon.svg';
	import IconSprite from '$lib/components/IconSprite.svelte';
	import Toast from '$lib/components/Toast.svelte';
	import { getMe } from '$lib/api/endpoints/home';
	import { loadNotifications } from '$lib/notifications';
	import { teacher } from '$lib/stores';

	let { children } = $props();

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
