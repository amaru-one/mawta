<script lang="ts">
	let { label = 'Cargando…' }: { label?: string } = $props();
</script>

<div class="mw-loading" role="status">
	<span class="mw-spinner" aria-hidden="true"></span><span>{label}</span>
</div>
