<script lang="ts">
	import { DesignSystem, ErrorNotice, LoadingState } from '$lib/design-system';
	import '../app.css';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import favicon from '$lib/assets/favicon.svg';
	import Toast from '$lib/components/Toast.svelte';
	import { getMe } from '$lib/api/endpoints/home';
	import { ApiError, setUnauthorizedHandler } from '$lib/api/client';
	import { loginHref } from '$lib/auth';
	import { loadNotifications } from '$lib/notifications';
	import { session, teacher } from '$lib/stores';

	let { children } = $props();

	let bootFailed = $state(false);
	let retrying = $state(false);

	// An expired session sends the teacher to login and back to this page.
	function goAnonymous(): void {
		session.set({ status: 'anonymous' });
		teacher.set(null);
		if (page.url.pathname !== '/login')
			void goto(loginHref(page.url.pathname + page.url.search), { replaceState: true });
	}

	async function boot(): Promise<void> {
		bootFailed = false;
		try {
			const me = await getMe();
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
			// A director only has /direccion; a teacher never sees it.
			const onDirector = page.url.pathname.startsWith('/direccion');
			if (me.role === 'director' && !onDirector) await goto('/direccion', { replaceState: true });
			if (me.role !== 'director' && onDirector) await goto('/', { replaceState: true });
			session.set({ status: 'authenticated', role: me.role });
			if (me.role === 'director') return;

			// Only loads once signed in — an unconditional load would spam
			// /notifications with 401s (each one re-triggering the redirect)
			// for as long as a viewer sits on /login.
			void loadNotifications().catch(() => {});
		} catch (error) {
			// A 401 already went through the unauthorized handler and redirected.
			if (error instanceof ApiError && error.status === 401) return;
			// Network or 5xx: the session may be fine. Say so and let the teacher retry
			// instead of silently sending them to login.
			bootFailed = true;
		} finally {
			retrying = false;
		}
	}

	onMount(() => {
		setUnauthorizedHandler(goAnonymous);

		// /login is never probed: firing GET /me there would 401 on a page
		// that's supposed to be reachable with no session at all.
		if (page.url.pathname === '/login') {
			session.set({ status: 'anonymous' });
			return;
		}

		void boot();
	});

	function retry(): void {
		retrying = true;
		void boot();
	}
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
</svelte:head>

<DesignSystem class="application">
	<div class="app-shell">
		{#if $session.status !== 'unknown'}
			{@render children()}
		{:else if bootFailed}
			<div class="body">
				<ErrorNotice
					message="No pudimos conectar con Mawta. Revisa tu conexión e inténtalo de nuevo."
					onretry={retry}
					{retrying}
				/>
			</div>
		{:else}
			<div class="body"><LoadingState label="Cargando Mawta…" /></div>
		{/if}
	</div>

	<Toast />
</DesignSystem>
