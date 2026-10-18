<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import ChatSidebar from '$lib/chat/ChatSidebar.svelte';
	import { chatList } from '$lib/chat/state.svelte';

	let { children } = $props();

	onMount(() => {
		void chatList.load();
	});

	// On a phone the list and a chat are two screens; from 1024 px they sit side by side.
	const inThread = $derived(Boolean(page.params.id));
</script>

<div class="chat-app" class:in-thread={inThread}>
	<aside class="chat-side" aria-label="Chats">
		<ChatSidebar />
	</aside>
	<div class="chat-main">
		{@render children()}
	</div>
</div>

<style>
	.chat-app {
		--chat-measure: 760px;
		display: grid;
		grid-template-columns: 300px 1fr;
		height: 100dvh;
		background: var(--mw-surface-card);
	}
	.chat-side {
		min-height: 0;
		border-right: 1px solid var(--mw-line);
	}
	.chat-main {
		display: flex;
		flex-direction: column;
		position: relative;
		min-width: 0;
		min-height: 0;
	}
	@media (max-width: 1023px) {
		.chat-app {
			grid-template-columns: 1fr;
		}
		.chat-side {
			border-right: 0;
		}
		.chat-app.in-thread .chat-side,
		.chat-app:not(.in-thread) .chat-main {
			display: none;
		}
	}
</style>
