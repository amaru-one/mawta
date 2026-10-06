<script lang="ts">
	import IconButton from './IconButton.svelte';
	let {
		title,
		index,
		total,
		noun = 'competencias',
		onprevious,
		onnext,
	}: {
		title: string;
		index: number;
		total: number;
		noun?: string;
		onprevious?: () => void;
		onnext?: () => void;
	} = $props();
</script>

<nav class="mw-stepnav" aria-label="Navegación entre {noun}">
	<IconButton
		icon="chevron-left"
		label="Anterior"
		outlined
		disabled={index <= 0 || !onprevious}
		onclick={onprevious}
	/>
	<div aria-live="polite">
		<p class="mw-text mw-text--body-strong">{title}</p>
		<p class="mw-meta">{total > 0 ? index + 1 : 0} de {total} {noun}</p>
	</div>
	<IconButton
		icon="chevron-right"
		label="Siguiente"
		outlined
		disabled={index >= total - 1 || !onnext}
		onclick={onnext}
	/>
</nav>
