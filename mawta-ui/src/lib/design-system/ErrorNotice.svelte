<script lang="ts">
	import Notice from './Notice.svelte';
	import Button from './Button.svelte';
	let {
		message,
		onretry,
		retrying = false,
	}: { message: string; onretry?: () => void; retrying?: boolean } = $props();
</script>

<div class="mw-error-notice">
	<Notice variant="danger" live>{message}</Notice>
	{#if onretry}<Button variant="secondary" loading={retrying} onclick={onretry}>Reintentar</Button
		>{/if}
</div>
