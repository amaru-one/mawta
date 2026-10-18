<script lang="ts">
	import type { TableBlock } from '../types';
	let { block }: { block: TableBlock } = $props();
	// A column is numeric when every value in it is a number: right-aligned,
	// tabular figures.
	const numeric = $derived(
		block.columnas.map(
			(_, i) => block.filas.length > 0 && block.filas.every((row) => typeof row[i] === 'number')
		)
	);
</script>

<section class="data-card">
	<h3 class="title">{block.titulo}</h3>
	<div class="wrap">
		<table>
			<thead>
				<tr>
					{#each block.columnas as column, i (i)}
						<th scope="col" class:num={numeric[i]}>{column}</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#each block.filas as row, r (r)}
					<tr>
						{#each row as value, i (i)}
							<td class:num={numeric[i]}>{value ?? '—'}</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
	{#if block.nota}<p class="note">{block.nota}</p>{/if}
</section>

<style>
	.data-card {
		min-width: 0;
		padding: var(--mw-space-3) var(--mw-space-4);
		border: 1px solid var(--mw-line);
		border-radius: var(--mw-radius-xl);
		background: var(--mw-surface-card);
		box-shadow: var(--mw-shadow-card);
	}
	.title {
		margin: var(--mw-space-1) 0 var(--mw-space-3);
		font-size: var(--mw-type-small-size);
		line-height: var(--mw-type-small-line);
		font-weight: 700;
	}
	.wrap {
		overflow-x: auto;
		margin: 0 calc(-1 * var(--mw-space-4));
		padding: 0 var(--mw-space-4);
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--mw-type-small-size);
		line-height: var(--mw-type-small-line);
	}
	th {
		padding: 0 var(--mw-space-3) var(--mw-space-2) 0;
		border-bottom: 1px solid var(--mw-line);
		color: var(--mw-ink-muted);
		font-size: var(--mw-type-caption-size);
		line-height: var(--mw-type-caption-line);
		font-weight: 700;
		text-align: left;
		white-space: nowrap;
	}
	td {
		padding: var(--mw-space-2) var(--mw-space-3) var(--mw-space-2) 0;
		border-bottom: 1px solid var(--mw-line);
		white-space: nowrap;
	}
	tr:last-child td {
		border-bottom: 0;
	}
	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.note {
		margin: var(--mw-space-3) 0 0;
		color: var(--mw-ink-muted);
		font-size: var(--mw-type-caption-size);
		line-height: var(--mw-type-caption-line);
	}
</style>
