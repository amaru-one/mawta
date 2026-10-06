<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	let {
		date,
		title,
		topics,
		evidence,
		off = false,
		detail = 'Sin clase · no se cuenta',
		actions,
		editor,
	}: {
		date: string;
		title: string;
		topics?: string;
		evidence?: { name: string; href?: string };
		off?: boolean;
		detail?: string;
		actions?: Snippet;
		editor?: Snippet;
	} = $props();
	// Parse calendar dates at UTC noon so host time zones cannot shift the classroom day.
	const parsed = $derived(new Date(`${date}T12:00:00Z`));
	const day = $derived(
		new Intl.DateTimeFormat('es-PE', { day: 'numeric', timeZone: 'UTC' }).format(parsed)
	);
	const weekday = $derived(
		new Intl.DateTimeFormat('es-PE', { weekday: 'short', timeZone: 'UTC' })
			.format(parsed)
			.replace('.', '')
	);
	const month = $derived(
		new Intl.DateTimeFormat('es-PE', { month: 'short', timeZone: 'UTC' })
			.format(parsed)
			.replace('.', '')
	);
</script>

<div class="mw-session {off ? 'mw-session--off' : ''}">
	<time class="mw-session__date" datetime={date}
		><span class="mw-session__day">{day}</span><span class="mw-session__dow">{weekday} {month}</span
		></time
	>
	<div class="mw-session__body">
		{#if editor}{@render editor()}{:else}<p class="mw-session__title">{title}</p>
			{#if off}<p class="mw-meta">{detail}</p>{:else}{#if topics}<p class="mw-meta">
						Temas: {topics}
					</p>{/if}{#if evidence}{#if evidence.href}<a
							class="mw-session__evidence"
							href={evidence.href}><Icon name="clipboard-check" />{evidence.name}</a
						>{:else}<p class="mw-session__evidence">
							<Icon name="clipboard-check" />{evidence.name}
						</p>{/if}{/if}{/if}{#if actions}<div class="mw-session__actions">
					{@render actions()}
				</div>{/if}
		{/if}
	</div>
</div>
