<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Button, Icon, IconButton, LoadingState, Notice } from '$lib/design-system';
	import { logout } from '$lib/api/endpoints/auth';
	import { session, teacher } from '$lib/stores';
	import { showToast } from '$lib/toast';
	import { groupThreads, threadMeta } from './groups';
	import { chatList } from './state.svelte';
	import { forgetChatToken } from './token';

	let creating = $state(false);
	const groups = $derived(groupThreads(chatList.threads));
	const currentId = $derived(page.params.id ?? null);

	async function newChat(): Promise<void> {
		creating = true;
		try {
			const thread = await chatList.create();
			await goto(`/direccion/${thread.id}`);
		} catch {
			showToast('No pudimos crear el chat. Inténtalo de nuevo.');
		} finally {
			creating = false;
		}
	}

	async function signOut(): Promise<void> {
		try {
			await logout();
		} catch {
			// handleLogout is idempotent and clears the cookie either way.
		}
		forgetChatToken();
		session.set({ status: 'anonymous' });
		teacher.set(null);
		await goto('/login', { replaceState: true });
	}
</script>

<div class="side">
	<header class="head">
		<p class="eyebrow">Dirección</p>
		<p class="school">{$teacher?.school ?? ''}</p>
	</header>

	<div class="new">
		<Button
			variant="primary"
			block
			icon="plus"
			loading={creating}
			disabled={chatList.status !== 'ready'}
			onclick={newChat}>Nuevo chat</Button
		>
	</div>

	<nav class="list" aria-label="Tus chats">
		{#if chatList.status === 'loading'}
			<LoadingState label="Cargando tus chats…" />
		{:else if chatList.status === 'unavailable'}
			<div class="notice">
				<Notice variant="attention">El chat de dirección aún no está disponible.</Notice>
			</div>
		{:else if chatList.status === 'error'}
			<div class="notice">
				<Notice variant="danger">No pudimos cargar tus chats.</Notice>
				<Button variant="secondary" onclick={() => chatList.load()}>Reintentar</Button>
			</div>
		{:else if chatList.threads.length === 0}
			<p class="empty">Aún no tienes chats. Empieza uno con “Nuevo chat”.</p>
		{:else}
			{#each groups as group (group.label)}
				<p class="group">{group.label}</p>
				{#each group.threads as thread (thread.id)}
					<a
						class="item"
						href="/direccion/{thread.id}"
						aria-current={thread.id === currentId ? 'page' : undefined}
					>
						<span class="item-title">{thread.title}</span>
						<span class="item-meta">{threadMeta(thread.updated_at)}</span>
					</a>
				{/each}
			{/each}
		{/if}
	</nav>

	<footer class="foot">
		<span class="avatar" aria-hidden="true">{$teacher?.initials ?? ''}</span>
		<span class="who">
			<span class="who-name">{$teacher?.shortName ?? ''}</span>
			<span class="who-role">Dirección</span>
		</span>
		<IconButton icon="logout" label="Cerrar sesión" onclick={signOut} />
	</footer>
</div>

<style>
	.side {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
	}
	.head {
		padding: var(--mw-space-5) var(--mw-space-4) var(--mw-space-3);
	}
	.eyebrow {
		margin: 0;
		color: var(--mw-ink-muted);
		font-size: var(--mw-type-label-size);
		line-height: var(--mw-type-label-line);
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}
	.school {
		margin: var(--mw-space-1) 0 0;
		font-size: var(--mw-type-heading-size);
		line-height: var(--mw-type-heading-line);
		font-weight: 800;
		letter-spacing: -0.01em;
	}
	.new {
		padding: 0 var(--mw-space-4) var(--mw-space-2);
	}
	.list {
		flex: 1;
		overflow-y: auto;
		padding: var(--mw-space-2) var(--mw-space-2) var(--mw-space-4);
	}
	.notice {
		display: grid;
		gap: var(--mw-space-2);
		padding: var(--mw-space-2);
	}
	.empty {
		margin: var(--mw-space-4) var(--mw-space-3);
		color: var(--mw-ink-muted);
		font-size: var(--mw-type-small-size);
		line-height: var(--mw-type-small-line);
	}
	.group {
		margin: var(--mw-space-4) var(--mw-space-2) var(--mw-space-1);
		color: var(--mw-ink-muted);
		font-size: var(--mw-type-label-size);
		line-height: var(--mw-type-label-line);
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}
	.item {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-height: var(--mw-touch-target);
		padding: var(--mw-space-2) var(--mw-space-3);
		border-radius: var(--mw-radius-md);
		text-decoration: none;
	}
	.item[aria-current='page'] {
		background: var(--mw-surface-tint);
	}
	@media (hover: hover) {
		.item:hover:not([aria-current='page']) {
			background: var(--mw-surface-page);
		}
	}
	.item-title {
		overflow: hidden;
		color: var(--mw-ink);
		font-size: var(--mw-type-small-size);
		line-height: var(--mw-type-small-line);
		font-weight: 600;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.item[aria-current='page'] .item-title {
		color: var(--mw-accent-pressed);
	}
	.item-meta {
		color: var(--mw-ink-muted);
		font-size: var(--mw-type-caption-size);
		line-height: var(--mw-type-caption-line);
	}
	@media (max-width: 1023px) {
		.item {
			min-height: 56px;
			padding: var(--mw-space-3);
		}
		.item-title {
			font-size: var(--mw-type-body-size);
			line-height: var(--mw-type-body-line);
		}
	}
	.foot {
		display: flex;
		align-items: center;
		gap: var(--mw-space-3);
		padding: var(--mw-space-3) var(--mw-space-4);
		padding-bottom: max(var(--mw-space-3), env(safe-area-inset-bottom));
		border-top: 1px solid var(--mw-line);
	}
	.avatar {
		display: flex;
		flex: 0 0 36px;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		border-radius: var(--mw-radius-full);
		background: var(--mw-surface-tint);
		color: var(--mw-accent);
		font-size: var(--mw-type-caption-size);
		font-weight: 800;
	}
	.who {
		display: flex;
		flex: 1;
		flex-direction: column;
		min-width: 0;
	}
	.who-name {
		overflow: hidden;
		font-size: var(--mw-type-small-size);
		line-height: var(--mw-type-small-line);
		font-weight: 700;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.who-role {
		color: var(--mw-ink-muted);
		font-size: var(--mw-type-caption-size);
		line-height: var(--mw-type-caption-line);
	}
</style>
