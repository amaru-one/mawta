<script lang="ts">
	import { goto } from '$app/navigation';
	import { chatList } from '$lib/chat/state.svelte';
	import Welcome from '$lib/chat/Welcome.svelte';
	import { showToast } from '$lib/toast';

	let starting = $state(false);

	// A suggestion opens a new chat and is sent from there.
	async function start(question: string): Promise<void> {
		starting = true;
		try {
			const thread = await chatList.create();
			chatList.pendingQuestion = question;
			await goto(`/direccion/${thread.id}`);
		} catch {
			showToast('No pudimos crear el chat. Inténtalo de nuevo.');
			starting = false;
		}
	}
</script>

<svelte:head>
	<title>Dirección</title>
</svelte:head>

<div class="home">
	<Welcome onpick={start} disabled={starting || chatList.status !== 'ready'} />
</div>

<style>
	.home {
		flex: 1;
		overflow-y: auto;
		padding: var(--mw-space-6) var(--mw-space-4) var(--mw-space-8);
	}
</style>
