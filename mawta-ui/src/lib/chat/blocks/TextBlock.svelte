<script lang="ts">
	import { renderMarkdown } from '../markdown';
	let { md, streaming = false }: { md: string; streaming?: boolean } = $props();
	// renderMarkdown escapes every character of the model's text before it
	// adds its own tags, so {@html} never renders markup the model wrote.
	const html = $derived(renderMarkdown(md));
</script>

<div class="text">
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html html}{#if streaming}<span class="caret" aria-hidden="true"></span>{/if}
</div>

<style>
	.text {
		color: var(--mw-ink);
		overflow-wrap: break-word;
	}
	.text :global(p),
	.text :global(ul),
	.text :global(ol) {
		margin: 0 0 var(--mw-space-3);
	}
	.text :global(p:last-child),
	.text :global(ul:last-child),
	.text :global(ol:last-child) {
		margin-bottom: 0;
	}
	.text :global(ul),
	.text :global(ol) {
		padding-left: var(--mw-space-5);
	}
	.text :global(li + li) {
		margin-top: var(--mw-space-1);
	}
	.text :global(strong) {
		font-weight: 700;
	}
	.text :global(code) {
		padding: 1px 4px;
		border-radius: var(--mw-radius-sm);
		background: var(--mw-surface-page);
		font-size: 0.92em;
	}
	.caret {
		display: inline-block;
		width: 2px;
		height: 1em;
		margin-left: 1px;
		vertical-align: -2px;
		background: var(--mw-ink-muted);
		animation: blink 1s steps(2) infinite;
	}
	@keyframes blink {
		50% {
			opacity: 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.caret {
			animation: none;
		}
	}
</style>
