<script lang="ts">
	import { hapticSuccess } from '$lib/haptics';
	import { areAllPresent, setAllPresent } from '$lib/lesson';
	import { enteredCount, students } from '$lib/stores';
	import { showToast } from '$lib/toast';

	let isComplete = $state(false);
	let showConfetti = $state(false);

	const allPresent = $derived(areAllPresent());
	const isAllEntered = $derived($enteredCount === $students.length && $students.length > 0);

	// Watch for completion
	$effect(() => {
		if (isAllEntered && !isComplete) {
			isComplete = true;
			showConfetti = true;
			hapticSuccess();
			// Trigger multiple haptic pulses for celebration
			setTimeout(() => hapticSuccess(), 100);
			setTimeout(() => hapticSuccess(), 200);
			// Stop confetti after animation
			setTimeout(() => {
				showConfetti = false;
			}, 2000);
		} else if (!isAllEntered && isComplete) {
			isComplete = false;
		}
	});

	function togglePresent(): void {
		const undo = setAllPresent();
		hapticSuccess();
		const message = allPresent ? 'Unmarked all present' : 'Marked all present';
		showToast(message, {
			onUndo: () => {
				undo.restore();
				showToast('Undo completed');
			}
		});
	}
</script>

{#if showConfetti}
	<div class="confetti-container">
		{#each Array.from({ length: 50 }) as _, i (i)}
			<div class="confetti" style="--delay: {i * 20}ms; --x: {Math.random() * 100}%; --rotation: {Math.random() * 360}deg;"></div>
		{/each}
	</div>
{/if}

<div class="bar" class:complete={isComplete} class:shake={isComplete}>
	<div class="info">
		<span class="counter" class:complete={isComplete}>
			{$enteredCount}/{$students.length}
			{#if isComplete}
				<span class="badge">✓ Complete</span>
			{:else}
				<span class="label">entered</span>
			{/if}
		</span>
	</div>
	<button class="btn-present pressable" class:active={allPresent} onclick={togglePresent}>
		<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
			<polyline points="20 6 9 17 4 12"></polyline>
		</svg>
		<span>{allPresent ? 'All Present' : 'Mark All Present'}</span>
	</button>
</div>

<style>
	@keyframes shake {
		0%, 100% { transform: translateX(0); }
		10% { transform: translateX(-8px); }
		20% { transform: translateX(8px); }
		30% { transform: translateX(-8px); }
		40% { transform: translateX(8px); }
		50% { transform: translateX(-8px); }
		60% { transform: translateX(8px); }
		70% { transform: translateX(-8px); }
		80% { transform: translateX(8px); }
		90% { transform: translateX(-4px); }
	}

	@keyframes glow-pulse {
		0%, 100% {
			box-shadow: 0 0 0 0 rgba(52, 199, 89, 0.4), 0 1px 0 rgba(0, 0, 0, 0.05);
		}
		50% {
			box-shadow: 0 0 0 8px rgba(52, 199, 89, 0), 0 1px 0 rgba(0, 0, 0, 0.05);
		}
	}

	@keyframes confetti-fall {
		to {
			transform: translateY(100vh) rotateZ(var(--rotation));
			opacity: 0;
		}
	}

	.confetti-container {
		position: fixed;
		top: 0;
		left: 0;
		width: 100%;
		height: 100%;
		pointer-events: none;
		z-index: 100;
		overflow: hidden;
	}

	.confetti {
		position: absolute;
		width: 8px;
		height: 8px;
		background: var(--primary);
		left: var(--x);
		top: -10px;
		animation: confetti-fall 2s ease-out forwards;
		animation-delay: var(--delay);
		border-radius: 50%;
	}

	.confetti:nth-child(odd) {
		background: #34c759;
	}

	.confetti:nth-child(3n) {
		background: #0ea5e9;
	}

	.confetti:nth-child(5n) {
		background: #f59e0b;
	}

	.bar {
		position: sticky;
		top: 0;
		z-index: 10;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-lg);
		background: rgba(255, 255, 255, 0.95);
		backdrop-filter: blur(10px);
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid rgba(0, 0, 0, 0.05);
		transition: all 150ms ease-out;
	}

	.bar.shake {
		animation: shake 0.9s ease-in-out;
	}

	.bar.complete {
		border-bottom: 2px solid #34c759;
		animation: glow-pulse 2s ease-out;
	}

	.info {
		display: flex;
		align-items: center;
	}

	.counter {
		font-size: 14px;
		font-weight: 500;
		font-variant-numeric: tabular-nums;
		color: var(--neutral-600);
		transition: all 150ms ease-out;
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.counter.complete {
		font-weight: 700;
		color: #34c759;
		font-size: 15px;
	}

	.counter .label {
		font-weight: 500;
		color: var(--neutral-600);
		font-size: 12px;
	}

	.counter .badge {
		font-weight: 600;
		color: #34c759;
		font-size: 12px;
		padding: 2px 8px;
		background: #ecfdf5;
		border-radius: 6px;
	}

	.btn-present {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 20px;
		min-height: 44px;
		border: none;
		border-radius: 22px;
		font-size: 14px;
		font-weight: 600;
		cursor: pointer;
		transition: all 150ms ease-out;
		white-space: nowrap;
		background: #f5f5f7;
		color: #1d1d1f;
	}

	.btn-present .icon {
		width: 18px;
		height: 18px;
		flex-shrink: 0;
		opacity: 0.7;
		transition: opacity 150ms ease-out;
	}

	.btn-present:hover {
		background: #e8e8eb;
	}

	.btn-present.active {
		background: #34c759;
		color: white;
		box-shadow: 0 4px 12px rgba(52, 199, 89, 0.2);
	}

	.btn-present.active .icon {
		opacity: 1;
	}

	.btn-present.active:hover {
		background: #30b452;
		box-shadow: 0 4px 16px rgba(52, 199, 89, 0.3);
	}
</style>
