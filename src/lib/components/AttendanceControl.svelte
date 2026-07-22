<script lang="ts">
	import type { Attendance } from '$lib/types';

	interface Props {
		value: Attendance | null;
		onchange: (value: Attendance) => void;
	}

	let { value, onchange }: Props = $props();

	function toggle(): void {
		onchange(value === 'present' ? 'absent' : 'present');
	}
</script>

<button
	class="badge pressable"
	class:present={value === 'present'}
	class:absent={value === 'absent'}
	class:unset={value === null}
	onclick={toggle}
	aria-label={value === 'present'
		? 'Marked present — tap to mark absent'
		: value === 'absent'
			? 'Marked absent — tap to mark present'
			: 'Attendance not set — tap to mark present'}
>
	<span class="icon" class:rotated={value === 'absent'}>
		{#if value === 'present'}✓{:else}○{/if}
	</span>
	{value ?? 'present?'}
</button>

<style>
	.badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 32px;
		min-width: 96px;
		justify-content: center;
		padding: 0 var(--space-md);
		border-radius: 16px;
		font-size: 14px;
		font-weight: 700;
		letter-spacing: 0.2px;
	}

	/* 44px minimum tap target via invisible padding halo */
	.badge {
		position: relative;
	}
	.badge::after {
		content: '';
		position: absolute;
		inset: -6px;
	}

	.present {
		background: linear-gradient(
			to bottom,
			color-mix(in srgb, var(--success) 95%, white),
			var(--success)
		);
		color: white;
	}

	.absent {
		background: linear-gradient(
			to bottom,
			color-mix(in srgb, var(--danger) 95%, white),
			var(--danger)
		);
		color: white;
	}

	.unset {
		background: var(--neutral-200);
		color: var(--neutral-600);
		border: 1px dashed var(--neutral-400);
	}

	.badge:active {
		box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.15);
	}

	.icon {
		display: inline-block;
		font-size: 13px;
		transition: transform 200ms ease-out;
	}

	.icon.rotated {
		transform: rotate(90deg);
	}
</style>
