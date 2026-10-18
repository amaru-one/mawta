<script lang="ts">
	import { tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError } from '$lib/api/client';
	import { ConfirmDialog, ErrorNotice, Icon, IconButton, LoadingState } from '$lib/design-system';
	import { ask, deleteThread, listMessages, renameThread } from '$lib/chat/api';
	import Blocks from '$lib/chat/blocks/Blocks.svelte';
	import Composer from '$lib/chat/Composer.svelte';
	import { dayLabel, sameDay, timeLabel } from '$lib/chat/groups';
	import { chatList } from '$lib/chat/state.svelte';
	import type { Block, Message, StreamEvent } from '$lib/chat/types';
	import Welcome from '$lib/chat/Welcome.svelte';
	import { showToast } from '$lib/toast';

	type Live = { question: string; status: string | null; blocks: Block[]; done: boolean };

	const id = $derived(page.params.id ?? '');
	const thread = $derived(chatList.threads.find((t) => t.id === id));

	let messages = $state<Message[]>([]);
	let loadState = $state<'loading' | 'ready' | 'missing' | 'error'>('loading');
	let live = $state<Live | null>(null);
	let controller: AbortController | null = null;

	let scroller: HTMLDivElement | undefined = $state();
	let showToBottom = $state(false);
	let menuOpen = $state(false);
	let renaming = $state(false);
	let newTitle = $state('');
	let confirmDelete = $state(false);

	async function load(threadId: string): Promise<void> {
		controller?.abort();
		live = null;
		loadState = 'loading';
		try {
			messages = await listMessages(threadId);
			loadState = 'ready';
			await scrollToEnd();
			const pending = chatList.pendingQuestion;
			if (pending) {
				chatList.pendingQuestion = null;
				void send(pending);
			}
		} catch (err) {
			loadState = err instanceof ApiError && err.status === 404 ? 'missing' : 'error';
		}
	}

	$effect(() => {
		void load(id);
	});

	function nearBottom(): boolean {
		if (!scroller) return true;
		return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
	}

	async function scrollToEnd(force = true): Promise<void> {
		const follow = force || nearBottom();
		await tick();
		if (scroller && follow) scroller.scrollTop = scroller.scrollHeight;
	}

	function onEvent(event: StreamEvent): void {
		if (!live) return;
		const blocks = live.blocks;
		if (event.tipo === 'estado') {
			live.status = (event as { texto: string }).texto;
		} else if (event.tipo === 'texto') {
			const delta = (event as { delta: string }).delta;
			const last = blocks.at(-1);
			if (last && last.tipo === 'texto') (last as { md: string }).md += delta;
			else blocks.push({ tipo: 'texto', md: delta });
			live.status = null;
		} else if (event.tipo === 'fin') {
			live.done = true;
		} else {
			const { version: _version, ...block } = event as { version: number } & Block;
			blocks.push(block as Block);
			live.status = null;
		}
		void scrollToEnd(false);
	}

	async function send(question: string): Promise<void> {
		if (live && !live.done) return;
		live = { question, status: 'Pensando…', blocks: [], done: false };
		controller = new AbortController();
		await scrollToEnd();
		try {
			await ask(id, question, onEvent, controller.signal);
			// The service saved both messages: show what it stored.
			messages = await listMessages(id);
			live = null;
			void chatList.refresh();
		} catch (err) {
			if (!live) return;
			if (controller.signal.aborted) {
				live.blocks.push({ tipo: 'texto', md: '_Respuesta detenida._' });
			} else {
				live.blocks.push({
					tipo: 'error',
					codigo: err instanceof ApiError ? err.code : 'network',
					mensaje: 'No pudimos enviar tu pregunta. Revisa tu conexión e inténtalo de nuevo.',
				});
			}
			live.status = null;
			live.done = true;
		} finally {
			controller = null;
			await scrollToEnd(false);
		}
	}

	function stop(): void {
		controller?.abort();
	}

	function retry(): void {
		const question = live?.question ?? lastQuestion();
		if (!question) return;
		void (async () => {
			messages = await listMessages(id).catch(() => messages);
			await send(question);
		})();
	}

	function lastQuestion(): string | null {
		const last = messages.findLast((m) => m.author === 'director');
		const block = last?.blocks[0] as { md?: string } | undefined;
		return block?.md ?? null;
	}

	function startRename(): void {
		menuOpen = false;
		newTitle = thread?.title ?? '';
		renaming = true;
	}

	async function saveRename(): Promise<void> {
		const title = newTitle.trim();
		renaming = false;
		if (!title || title === thread?.title) return;
		try {
			chatList.replace(await renameThread(id, title));
		} catch {
			showToast('No pudimos cambiar el nombre.');
		}
	}

	async function remove(): Promise<void> {
		confirmDelete = false;
		try {
			await deleteThread(id);
			chatList.remove(id);
			showToast('Chat eliminado');
			await goto('/direccion', { replaceState: true });
		} catch {
			showToast('No pudimos eliminar el chat.');
		}
	}

	function focusOnMount(node: HTMLInputElement): void {
		node.focus();
		node.select();
	}
</script>

<svelte:head>
	<title>{thread?.title ?? 'Chat'} · Dirección</title>
</svelte:head>

<svelte:window
	onclick={(event) => {
		if (menuOpen && !(event.target as Element).closest('.menu, .menu-toggle')) menuOpen = false;
	}}
	onkeydown={(event) => {
		if (event.key === 'Escape') menuOpen = false;
	}}
/>

<header class="bar">
	<a class="back" href="/direccion" aria-label="Volver a tus chats"
		><Icon name="arrow-left" size={20} /></a
	>
	{#if renaming}
		<input
			class="rename"
			aria-label="Nombre del chat"
			maxlength="200"
			bind:value={newTitle}
			use:focusOnMount
			onblur={saveRename}
			onkeydown={(event) => {
				if (event.key === 'Enter') void saveRename();
				if (event.key === 'Escape') renaming = false;
			}}
		/>
	{:else}
		<h1 class="title">{thread?.title ?? 'Chat'}</h1>
	{/if}
	<span class="menu-toggle">
		<IconButton
			icon="dots"
			label="Opciones del chat"
			aria-haspopup="menu"
			aria-expanded={menuOpen}
			onclick={() => (menuOpen = !menuOpen)}
		/>
	</span>
	{#if menuOpen}
		<div class="menu" role="menu">
			<button role="menuitem" type="button" onclick={startRename}>
				<Icon name="pencil" size={18} />Cambiar nombre
			</button>
			<button
				role="menuitem"
				type="button"
				class="danger"
				onclick={() => {
					menuOpen = false;
					confirmDelete = true;
				}}
			>
				<Icon name="trash" size={18} />Eliminar chat
			</button>
		</div>
	{/if}
</header>

<div
	class="thread"
	bind:this={scroller}
	onscroll={() => (showToBottom = !nearBottom())}
	role="log"
	aria-live="polite"
	aria-busy={live !== null && !live.done}
>
	<div class="inner">
		{#if loadState === 'loading'}
			<LoadingState label="Cargando el chat…" />
		{:else if loadState === 'missing'}
			<ErrorNotice message="Este chat ya no existe." />
			<a class="link" href="/direccion">Volver a tus chats</a>
		{:else if loadState === 'error'}
			<ErrorNotice message="No pudimos cargar este chat." onretry={() => load(id)} />
		{:else if messages.length === 0 && !live}
			<Welcome onpick={send} />
		{:else}
			{#each messages as message, i (message.id)}
				{#if i === 0 || !sameDay(messages[i - 1].created_at, message.created_at)}
					<p class="day">{dayLabel(message.created_at)}</p>
				{/if}
				{#if message.author === 'director'}
					<div class="mine">
						<div class="bubble">{(message.blocks[0] as { md?: string })?.md ?? ''}</div>
						<p class="time">{timeLabel(message.created_at)}</p>
					</div>
				{:else}
					<div class="answer">
						<Blocks
							blocks={message.blocks}
							onretry={i === messages.length - 1 ? retry : undefined}
						/>
						<p class="time">{timeLabel(message.created_at)}</p>
					</div>
				{/if}
			{/each}
			{#if live}
				<div class="mine">
					<div class="bubble">{live.question}</div>
				</div>
				<div class="answer">
					<Blocks blocks={live.blocks} streaming={!live.done} onretry={retry} />
					{#if live.status}
						<p class="status" role="status">
							<span class="spinner" aria-hidden="true"></span>{live.status}
						</p>
					{/if}
				</div>
			{/if}
		{/if}
	</div>
</div>

{#if showToBottom}
	<button class="to-bottom" type="button" onclick={() => scrollToEnd()}>
		<Icon name="arrow-down" size={16} />Ir al final
	</button>
{/if}

<Composer
	busy={live !== null && !live.done}
	disabled={loadState !== 'ready'}
	onsend={send}
	onstop={stop}
/>

<ConfirmDialog
	bind:open={confirmDelete}
	title="¿Eliminar este chat?"
	description="Se borra la conversación completa. No se puede deshacer."
	confirmLabel="Eliminar"
	tone="danger"
	onconfirm={remove}
/>

<style>
	.bar {
		display: flex;
		position: relative;
		align-items: center;
		gap: var(--mw-space-2);
		min-height: 64px;
		padding: var(--mw-space-2) var(--mw-space-3);
		border-bottom: 1px solid var(--mw-line);
	}
	.back {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: var(--mw-touch-target);
		height: var(--mw-touch-target);
		border-radius: var(--mw-radius-md);
		color: var(--mw-ink-secondary);
	}
	@media (min-width: 1024px) {
		.back {
			display: none;
		}
	}
	.title {
		flex: 1;
		min-width: 0;
		margin: 0;
		overflow: hidden;
		font-size: var(--mw-type-heading-size);
		line-height: var(--mw-type-heading-line);
		font-weight: 700;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.rename {
		flex: 1;
		min-width: 0;
		min-height: var(--mw-touch-target);
		padding: 0 var(--mw-space-3);
		border: 1px solid var(--mw-line-control);
		border-radius: var(--mw-radius-md);
		font-weight: 700;
	}
	.menu {
		position: absolute;
		top: 58px;
		right: var(--mw-space-3);
		z-index: var(--mw-z-overlay);
		min-width: 200px;
		padding: var(--mw-space-1);
		border: 1px solid var(--mw-line);
		border-radius: var(--mw-radius-lg);
		background: var(--mw-surface-card);
		box-shadow: var(--mw-shadow-raised);
	}
	.menu button {
		display: flex;
		align-items: center;
		gap: var(--mw-space-3);
		width: 100%;
		min-height: var(--mw-touch-target);
		padding: 0 var(--mw-space-3);
		border-radius: var(--mw-radius-md);
		font-size: var(--mw-type-small-size);
		font-weight: 600;
		text-align: left;
	}
	.menu .danger {
		color: var(--mw-danger);
	}
	@media (hover: hover) {
		.menu button:hover {
			background: var(--mw-surface-page);
		}
	}
	.thread {
		flex: 1;
		overflow-y: auto;
		padding: var(--mw-space-6) var(--mw-space-4) var(--mw-space-8);
	}
	.inner {
		display: flex;
		flex-direction: column;
		gap: var(--mw-space-6);
		max-width: var(--chat-measure);
		margin: 0 auto;
	}
	.day {
		align-self: center;
		margin: 0;
		color: var(--mw-ink-muted);
		font-size: var(--mw-type-caption-size);
		line-height: var(--mw-type-caption-line);
		font-weight: 600;
	}
	.mine {
		align-self: flex-end;
		max-width: min(85%, 560px);
	}
	.bubble {
		padding: var(--mw-space-3) var(--mw-space-4);
		border-radius: var(--mw-radius-xl) var(--mw-radius-xl) var(--mw-radius-sm) var(--mw-radius-xl);
		background: var(--mw-surface-tint);
		overflow-wrap: break-word;
		white-space: pre-wrap;
	}
	.answer {
		display: flex;
		flex-direction: column;
		gap: var(--mw-space-4);
		min-width: 0;
	}
	.time {
		margin: var(--mw-space-1) 0 0;
		color: var(--mw-ink-muted);
		font-size: var(--mw-type-caption-size);
		line-height: var(--mw-type-caption-line);
	}
	.mine .time {
		text-align: right;
	}
	.answer .time {
		margin-top: calc(-1 * var(--mw-space-3));
	}
	.status {
		display: flex;
		align-items: center;
		gap: var(--mw-space-2);
		margin: 0;
		color: var(--mw-ink-muted);
		font-size: var(--mw-type-small-size);
		line-height: var(--mw-type-small-line);
	}
	.spinner {
		flex: 0 0 14px;
		width: 14px;
		height: 14px;
		border: 2px solid currentColor;
		border-right-color: transparent;
		border-radius: 50%;
		animation: spin 800ms linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.spinner {
			animation: none;
		}
	}
	.link {
		color: var(--mw-accent);
		font-weight: 700;
	}
	.to-bottom {
		display: inline-flex;
		position: absolute;
		bottom: 120px;
		left: 50%;
		align-items: center;
		gap: var(--mw-space-1);
		min-height: 36px;
		padding: 0 var(--mw-space-3);
		transform: translateX(-50%);
		border: 1px solid var(--mw-line);
		border-radius: var(--mw-radius-full);
		background: var(--mw-surface-card);
		box-shadow: var(--mw-shadow-raised);
		color: var(--mw-ink-secondary);
		font-size: var(--mw-type-caption-size);
		font-weight: 700;
	}
</style>
