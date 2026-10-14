<script lang="ts">
	import Action from './Action.svelte';

	// The one action row for planned items (criteria, evidences, sessions):
	// accept while Mawta's proposal is pending, then edit, then remove at the end.
	let {
		proposal = false,
		onaccept,
		onedit,
		onremove,
	}: {
		proposal?: boolean;
		onaccept: () => void;
		onedit: () => void;
		onremove: () => void;
	} = $props();
</script>

<div class="mw-item-actions">
	{#if proposal}
		<Action variant="main" icon="check" onclick={onaccept}>Aceptar</Action>
	{/if}
	<Action variant="link" onclick={onedit}>Editar</Action>
	<span class="mw-item-actions__spacer"></span>
	<Action variant="remove" icon="trash" onclick={onremove}>Quitar</Action>
</div>

<style>
	.mw-item-actions {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--mw-space-2);
	}

	.mw-item-actions__spacer {
		flex: 1;
	}
</style>
