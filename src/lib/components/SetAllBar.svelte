<script lang="ts">
	import { hapticSuccess } from '$lib/haptics';
	import { setAllParticipated, setAllPresent } from '$lib/lesson';
	import { enteredCount, students } from '$lib/stores';
	import { showToast } from '$lib/toast';

	let glowing = $state(false);

	function glow(): void {
		glowing = true;
		setTimeout(() => (glowing = false), 300);
	}

	function allPresent(): void {
		const undo = setAllPresent();
		hapticSuccess();
		glow();
		showToast('All marked present', {
			onUndo: () => {
				undo.restore();
				showToast('Undo completed');
			}
		});
	}

	function allParticipated(): void {
		const undo = setAllParticipated();
		hapticSuccess();
		glow();
		showToast('All marked as participated', {
			onUndo: () => {
				undo.restore();
				showToast('Undo completed');
			}
		});
	}
</script>

<div class="bar" class:glowing>
	<span class="label">Set all:</span>
	<button class="action pressable" onclick={allPresent}>Present</button>
	<button class="action pressable" onclick={allParticipated}>Participated</button>
	<span class="counter">{$enteredCount}/{$students.length} entered</span>
</div>

<style>
	.bar {
		position: sticky;
		top: 0;
		z-index: 10;
		display: flex;
		align-items: center;
		gap: var(--space-md);
		background: var(--primary-light);
		color: var(--primary-dark);
		padding: var(--space-sm) var(--space-lg);
		border-radius: var(--radius-md);
		transition: box-shadow 150ms ease-out;
	}

	.bar.glowing {
		box-shadow: var(--shadow-primary);
	}

	.label {
		font-size: 14px;
		font-weight: 700;
		letter-spacing: 0.3px;
	}

	.action {
		background: white;
		color: var(--primary);
		border: 1px solid var(--neutral-200);
		border-radius: var(--radius-sm);
		padding: 0 var(--space-md);
		min-height: 44px;
		font-size: 14px;
		font-weight: 700;
	}

	.action:hover {
		background: var(--neutral-50);
		box-shadow: var(--shadow-sm);
	}

	.counter {
		margin-left: auto;
		font-size: 12px;
		font-weight: 500;
		font-variant-numeric: tabular-nums;
	}
</style>
