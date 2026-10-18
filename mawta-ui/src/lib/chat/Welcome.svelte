<script lang="ts">
	import { Icon } from '$lib/design-system';
	import { teacher } from '$lib/stores';

	let { onpick, disabled = false }: { onpick: (question: string) => void; disabled?: boolean } =
		$props();

	// Level 0 answers only about the school's sections; these grow with the tools.
	const SUGGESTIONS = [
		'¿Qué secciones tiene mi colegio?',
		'¿Cuántas secciones hay por grado?',
		'¿Qué secciones son del turno tarde?',
		'¿Qué puedes responder por ahora?',
	];

	const firstName = $derived(($teacher?.shortName ?? '').split(' ')[0]);
</script>

<div class="welcome">
	<h2 class="title">{firstName ? `Hola, ${firstName}` : 'Hola'}</h2>
	<p class="sub">¿Qué quieres saber de tu colegio?</p>
	<div class="suggest">
		{#each SUGGESTIONS as suggestion (suggestion)}
			<button type="button" {disabled} onclick={() => onpick(suggestion)}>
				<Icon name="chart" size={18} />
				<span>{suggestion}</span>
			</button>
		{/each}
	</div>
</div>

<style>
	.welcome {
		max-width: var(--chat-measure, 760px);
		margin: 0 auto;
		padding-top: 8vh;
	}
	.title {
		margin: 0;
		font-size: var(--mw-type-title-size);
		line-height: var(--mw-type-title-line);
		font-weight: 800;
		letter-spacing: -0.03em;
	}
	.sub {
		margin: var(--mw-space-2) 0 var(--mw-space-6);
		color: var(--mw-ink-muted);
	}
	.suggest {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
		gap: var(--mw-space-2);
	}
	.suggest button {
		display: flex;
		align-items: center;
		gap: var(--mw-space-3);
		min-height: 56px;
		padding: var(--mw-space-3) var(--mw-space-4);
		border: 1px solid var(--mw-line);
		border-radius: var(--mw-radius-lg);
		background: var(--mw-surface-card);
		color: var(--mw-ink-secondary);
		font-size: var(--mw-type-small-size);
		line-height: var(--mw-type-small-line);
		text-align: left;
	}
	.suggest button :global(.mw-icon) {
		color: var(--mw-ink-muted);
	}
	@media (hover: hover) {
		.suggest button:hover:not(:disabled) {
			border-color: var(--mw-line-control);
			color: var(--mw-ink);
		}
	}
</style>
