<script lang="ts">
	import type { StatusItem } from './types';
	import Icon from './Icon.svelte';
	let { items, label = 'Estado de las competencias' }: { items: StatusItem[]; label?: string } =
		$props();
</script>

<ul class="mw-status" aria-label={label}>
	{#each items as item (item.id)}<li class="mw-status__item mw-status__item--{item.status}">
			<span class="mw-status__marker" aria-hidden="true"
				>{#if item.status === 'done'}<Icon name="check" />{/if}</span
			>
			<div class="mw-status__content">
				<p class="mw-status__name">{item.name}</p>
				<p class="mw-status__label">{item.label}</p>
				{#if item.detail}<p class="mw-meta">{item.detail}</p>{/if}
			</div>
		</li>{/each}
</ul>
