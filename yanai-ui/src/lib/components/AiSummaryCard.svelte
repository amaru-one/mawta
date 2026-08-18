<script lang="ts">
	import Icon from './Icon.svelte';

	interface Props {
		title: string;
		bullets: string[];
	}

	let { title, bullets }: Props = $props();
</script>

<!-- Assistant-generated content: accent-tinted so it reads as machine output. -->
<div class="ai-card">
	<div class="row head">
		<Icon name="sparkles" size={14} />
		<p class="title">{title}</p>
	</div>
	<ul>
		{#each bullets as bullet (bullet)}
			<li>{bullet}</li>
		{/each}
	</ul>
</div>

<style>
	.ai-card {
		background: var(--bg-accent);
		border: 0.5px solid var(--fill-accent);
		border-radius: var(--radius-lg);
		padding: 14px var(--space-lg);
	}

	.head {
		gap: 6px;
		margin-bottom: 10px;
		color: var(--text-accent);
	}

	.title {
		margin: 0;
		font-size: 12px;
		font-weight: 500;
	}

	ul {
		margin: 0;
		padding-left: 18px;
	}

	li {
		font-size: 13px;
	}

	li:not(:last-child) {
		margin-bottom: 6px;
	}
</style>
