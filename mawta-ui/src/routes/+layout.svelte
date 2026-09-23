<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { afterNavigate, goto } from '$app/navigation';
	import { page } from '$app/state';
	import favicon from '$lib/assets/favicon.svg';
	import IconSprite from '$lib/components/IconSprite.svelte';
	import Toast from '$lib/components/Toast.svelte';
	import { getMe } from '$lib/api/endpoints/home';
	import { setUnauthorizedHandler } from '$lib/api/client';
	import { loadNotifications } from '$lib/notifications';
	import { canGoBack, session, teacher, usesInternalGrading } from '$lib/stores';

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

	let pollHandle: ReturnType<typeof setInterval> | undefined;

	function goAnonymous(): void {
		session.set({ status: 'anonymous' });
		teacher.set(null);
		if (pollHandle) {
			clearInterval(pollHandle);
			pollHandle = undefined;
		}
		if (page.url.pathname !== '/login') void goto('/login', { replaceState: true });
	}

	onMount(() => {
		setUnauthorizedHandler(goAnonymous);

		// /login is never probed: firing GET /me there would 401 on a page
		// that's supposed to be reachable with no session at all.
		if (page.url.pathname === '/login') {
			session.set({ status: 'anonymous' });
			return;
		}

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
					school: me.tenant.name,
				});
				usesInternalGrading.set(me.tenant.uses_internal_grading);
				session.set({ status: 'authenticated', role: me.role });

				// Only polls once signed in — unconditional polling would spam
				// /notifications with 401s (each one re-triggering the redirect)
				// for as long as a viewer sits on /login.
				void loadNotifications().catch(() => {});
				pollHandle = setInterval(() => void loadNotifications().catch(() => {}), 60_000);
			})
			.catch(() => {
				// A non-401 failure (network, 5xx) also lands here since
				// setUnauthorizedHandler only fires on 401; either way there is
				// no usable session, so the shell falls back the same way.
				goAnonymous();
			});

		return () => {
			if (pollHandle) clearInterval(pollHandle);
		};
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
</svelte:head>

<IconSprite />

<div class="app-shell">
	{#if $session.status !== 'unknown'}
		{@render children()}
	{/if}
</div>

<Toast />
