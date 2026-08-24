<script lang="ts">
	interface Props {
		pct: number | null;
		label: string;
		size?: number;
	}

	let { pct, label, size = 52 }: Props = $props();

	const r = $derived((size - 5) / 2);
	const circumference = $derived(2 * Math.PI * r);
	const dash = $derived(`${circumference * (pct ?? 0)} ${circumference}`);
</script>

<div class="ring" style="width:{size}px">
	<div class="svg-wrap" style="width:{size}px;height:{size}px">
		<svg width={size} height={size} viewBox="0 0 {size} {size}" style="transform:rotate(-90deg)">
			<circle cx={size / 2} cy={size / 2} {r} fill="none" stroke="var(--surface-1)" stroke-width="5" />
			{#if pct != null}
				<circle
					cx={size / 2}
					cy={size / 2}
					{r}
					fill="none"
					stroke="var(--fill-accent)"
					stroke-width="5"
					stroke-linecap="round"
					stroke-dasharray={dash}
				/>
			{/if}
		</svg>
		<span class="value" class:muted={pct == null}>
			{pct != null ? `${Math.round(pct * 100)}%` : '0%'}
		</span>
	</div>
	<p class="label">{label}</p>
</div>

<style>
	.ring {
		text-align: center;
		flex-shrink: 0;
	}

	.svg-wrap {
		position: relative;
	}

	.value {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 11px;
		font-weight: 600;
	}

	.value.muted {
		color: var(--text-muted);
	}

	.label {
		margin: 6px 0 0;
		font-size: 11px;
		color: var(--text-secondary);
	}
</style>
