<script lang="ts">
	import type { Capability } from './types';
	let {
		capabilities,
		label = 'Capacidades que miran tus criterios',
	}: { capabilities: Capability[]; label?: string } = $props();
	const missing = $derived(capabilities.filter((item) => !item.covered).map((item) => item.label));
</script>

<div class="mw-context">
	<p class="mw-text mw-text--label">{label}</p>
	<ul class="mw-meter" style:--n={Math.max(1, capabilities.length)}>
		{#each capabilities as item (item.id)}<li
				class="mw-meter__seg {item.covered ? 'mw-meter__seg--ok' : ''}"
			>
				<span class="mw-meter__bar" aria-hidden="true"></span><span
					>{item.label}<span class="mw-sr-only">: {item.covered ? 'cubierta' : 'falta'}</span></span
				>
			</li>{/each}
	</ul>
	<p class="mw-meta">
		{capabilities.length === 0
			? 'Sin capacidades'
			: missing.length
				? `Falta: ${missing.join(', ')}`
				: 'Todas las capacidades cubiertas'}
	</p>
</div>
