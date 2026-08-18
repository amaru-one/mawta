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

	const label = $derived(
		value === 'present' ? '✓ Presente' : value === 'absent' ? 'Ausente' : 'Marcar'
	);
</script>

<button
	class="attendance pressable"
	class:pill-dark={value === 'present'}
	class:pill-light={value !== 'present'}
	class:absent={value === 'absent'}
	class:unset={value === null}
	onclick={toggle}
	aria-label={value === 'present'
		? 'Presente — toca para marcar ausente'
		: value === 'absent'
			? 'Ausente — toca para marcar presente'
			: 'Sin marcar — toca para marcar presente'}
>
	{label}
</button>

<style>
	.attendance {
		position: relative;
		white-space: nowrap;
	}

	/* 44px minimum tap target via an invisible halo. */
	.attendance::after {
		content: '';
		position: absolute;
		inset: -10px;
	}

	.absent {
		color: var(--text-primary);
		background: var(--bg-danger);
	}

	.unset {
		border: 0.5px dashed var(--border-strong);
		color: var(--text-muted);
	}
</style>
