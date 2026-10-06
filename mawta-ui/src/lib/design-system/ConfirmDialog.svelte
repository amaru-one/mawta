<script lang="ts">
	import Dialog from './Dialog.svelte';
	import Button from './Button.svelte';
	let {
		open = $bindable(false),
		title,
		description,
		confirmLabel,
		cancelLabel = 'Cancelar',
		onconfirm,
		oncancel,
	}: {
		open?: boolean;
		title: string;
		description: string;
		confirmLabel: string;
		cancelLabel?: string;
		onconfirm: () => void;
		oncancel?: () => void;
	} = $props();
	let confirmed = false;
	function confirm() {
		confirmed = true;
		open = false;
		onconfirm();
	}
	function closed() {
		if (!confirmed) oncancel?.();
		confirmed = false;
	}
</script>

<Dialog bind:open {title} {description} role="alertdialog" onclose={closed}>
	{#snippet actions()}<Button
			onclick={() => {
				open = false;
			}}>{cancelLabel}</Button
		><Button variant="primary" onclick={confirm}>{confirmLabel}</Button>{/snippet}
</Dialog>
