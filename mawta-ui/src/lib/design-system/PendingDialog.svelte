<script lang="ts">
	import Dialog from './Dialog.svelte';
	import Button from './Button.svelte';
	let {
		open = $bindable(false),
		count,
		onreview,
		oncontinue,
	}: {
		open?: boolean;
		count: number;
		onreview: () => void;
		oncontinue: () => void;
	} = $props();
	const title = $derived(
		count === 1 ? 'Queda 1 propuesta sin revisar' : `Quedan ${count} propuestas sin revisar`
	);
</script>

<Dialog
	bind:open
	{title}
	description="Puedes revisarlas ahora o seguir. Las que no aceptes quedan sin aceptar."
>
	{#snippet actions()}<Button
			onclick={() => {
				open = false;
				onreview();
			}}>Revisar</Button
		><Button
			variant="primary"
			onclick={() => {
				open = false;
				oncontinue();
			}}>Continuar de todos modos</Button
		>{/snippet}
</Dialog>
