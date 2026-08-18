<script lang="ts">
	import Icon from './Icon.svelte';

	interface Props {
		flagged: boolean;
		onchange: (value: boolean) => void;
	}

	let { flagged, onchange }: Props = $props();
</script>

<button
	class="circ pressable"
	class:on={flagged}
	onclick={() => onchange(!flagged)}
	aria-pressed={flagged}
	aria-label={flagged ? 'Quitar marca de comportamiento' : 'Marcar comportamiento'}
	title={flagged ? 'Marcado' : 'Marcar comportamiento'}
>
	<Icon name="flag" size={14} />
</button>

<style>
	.circ {
		position: relative;
		background: var(--surface-1);
		color: var(--text-muted);
	}

	/* 44px minimum tap target via an invisible halo. */
	.circ::after {
		content: '';
		position: absolute;
		inset: -9px;
	}

	.on {
		background: var(--fill-danger);
		color: var(--on-danger);
	}
</style>
