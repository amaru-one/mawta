<script lang="ts">
	import Button from './Button.svelte';
	import Icon from './Icon.svelte';

	// Shown above a list while Mawta's proposal is pending. The bulk action only
	// appears for two or more proposals; one proposal is accepted on its card.
	let {
		message,
		count,
		label,
		loading = false,
		progress,
		onaccept,
	}: {
		message: string;
		count: number;
		label: string;
		loading?: boolean;
		progress?: string;
		onaccept: () => void;
	} = $props();
</script>

<div class="mw-proposal-bar">
	<p class="mw-meta">{message}</p>
	{#if count > 1}
		<Button variant="secondary" {loading} disabled={loading} onclick={onaccept}>
			{#if !loading}<Icon name="check" size={15} />{/if}
			{loading && progress ? progress : `${label} (${count})`}
		</Button>
	{/if}
</div>

<style>
	.mw-proposal-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--mw-space-2);
		margin: 0 0 var(--mw-space-2);
	}

	.mw-proposal-bar p {
		margin: 0;
	}
</style>
