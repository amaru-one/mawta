<script lang="ts">
	import { slide } from 'svelte/transition';
	import { hapticTap } from '$lib/haptics';
	import { chooseAssessment, createAssessment, sessionMode, setMode } from '$lib/lesson';
	import { assessments, currentCourse, currentSession } from '$lib/stores';
	import { showToast } from '$lib/toast';
	import type { Assessment, SessionMode } from '$lib/types';

	const MODES: Array<{ id: SessionMode; label: string }> = [
		{ id: 'lesson', label: 'Just lesson' },
		{ id: 'lesson+assessment', label: 'Lesson + quiz' },
		{ id: 'assessment', label: 'Assessment only' }
	];

	let newName = $state('');
	let newType = $state<Assessment['type']>('quiz');
	let newMaxScore = $state('');
	let invalid = $state(false);

	const needsAssessment = $derived($sessionMode !== 'lesson');
	const chosenAssessmentId = $derived(
		$currentSession?.blocks.find((b) => b.kind === 'assessment')?.assessmentId ?? ''
	);
	const lessonTopic = $derived(
		$currentSession?.blocks.find((b) => b.kind === 'lesson')?.topic ?? 'fractions'
	);

	const dateLabel = $derived(
		$currentSession
			? new Date($currentSession.date).toLocaleDateString('en-GB', {
					weekday: 'short',
					day: 'numeric',
					month: 'short'
				})
			: ''
	);

	const planLabel = $derived(
		$sessionMode === 'lesson'
			? `lesson (${lessonTopic})`
			: $sessionMode === 'lesson+assessment'
				? `lesson (${lessonTopic}) + assessment`
				: 'assessment'
	);

	function pickMode(mode: SessionMode): void {
		hapticTap();
		setMode(mode);
	}

	function pickExisting(event: Event): void {
		const id = (event.currentTarget as HTMLSelectElement).value;
		if (!id) return;
		chooseAssessment(id);
		showToast('Assessment added');
	}

	async function submitNew(): Promise<void> {
		const score = Number(newMaxScore);
		if (!newName.trim() || !Number.isFinite(score) || score <= 0) {
			invalid = true;
			showToast('Please fill all fields');
			return;
		}
		invalid = false;
		await createAssessment(newName.trim(), newType, score);
		newName = '';
		newMaxScore = '';
		showToast('Assessment added');
	}
</script>

<header class="header">
	<div class="title-line">
		<h1>{$currentCourse?.name ?? ''}</h1>
		<span class="when">
			· {dateLabel} · {$currentSession?.startTime}–{$currentSession?.endTime}
		</span>
	</div>
	<p class="plan">Your plan: {planLabel}</p>

	<div class="modes" role="radiogroup" aria-label="Session mode">
		{#each MODES as mode (mode.id)}
			<button
				class="chip pressable"
				class:active={$sessionMode === mode.id}
				role="radio"
				aria-checked={$sessionMode === mode.id}
				onclick={() => pickMode(mode.id)}
			>
				{mode.label}
			</button>
		{/each}
	</div>

	{#if needsAssessment}
		<div class="assessment-form" transition:slide={{ duration: 150 }}>
			<label class="field">
				<span>Use existing:</span>
				<select value={chosenAssessmentId} onchange={pickExisting}>
					<option value="" disabled>choose…</option>
					{#each $assessments as a (a.id)}
						<option value={a.id}>{a.name} ({a.status})</option>
					{/each}
				</select>
			</label>
			<span class="or">or create new:</span>
			<input
				class:invalid={invalid && !newName.trim()}
				type="text"
				placeholder="name"
				bind:value={newName}
			/>
			<select bind:value={newType}>
				<option value="quiz">quiz</option>
				<option value="midterm">midterm</option>
				<option value="final">final</option>
			</select>
			<input
				class="score"
				class:invalid={invalid && !(Number(newMaxScore) > 0)}
				type="number"
				placeholder="max"
				min="1"
				bind:value={newMaxScore}
			/>
			<button class="use pressable" onclick={submitNew}>Use</button>
		</div>
	{/if}
</header>

<style>
	.header {
		padding: var(--space-sm) 0 var(--space-lg);
	}

	.title-line {
		display: flex;
		align-items: baseline;
		gap: var(--space-sm);
		flex-wrap: wrap;
	}

	h1 {
		margin: 0;
		font-size: 24px;
		line-height: 32px;
		font-weight: 700;
		letter-spacing: 0.3px;
	}

	.when {
		font-size: 14px;
		color: var(--neutral-600);
	}

	.plan {
		margin: var(--space-xs) 0 var(--space-md);
		font-size: 14px;
		color: var(--neutral-600);
	}

	.modes {
		display: flex;
		gap: var(--space-sm);
		flex-wrap: wrap;
	}

	.chip {
		min-height: 44px;
		padding: 0 var(--space-lg);
		border-radius: 22px;
		font-size: 14px;
		font-weight: 500;
		background: var(--neutral-200);
		color: var(--neutral-700);
	}

	.chip:hover:not(.active) {
		background: var(--neutral-300);
	}

	.chip.active {
		background: var(--primary);
		color: white;
	}

	.assessment-form {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		flex-wrap: wrap;
		margin-top: var(--space-md);
		background: var(--primary-light);
		border-radius: var(--radius-md);
		padding: var(--space-sm) var(--space-md);
		font-size: 14px;
		color: var(--primary-dark);
	}

	.field {
		display: inline-flex;
		align-items: center;
		gap: var(--space-sm);
		font-weight: 500;
	}

	.or {
		color: var(--neutral-600);
	}

	select,
	input {
		height: 36px;
		border: 1px solid var(--neutral-300);
		border-radius: var(--radius-sm);
		padding: 0 var(--space-sm);
		background: white;
		transition: border-color 100ms ease-out;
	}

	input.invalid {
		border-color: var(--danger);
	}

	input[type='text'] {
		width: 130px;
	}

	.score {
		width: 64px;
	}

	.use {
		min-height: 36px;
		padding: 0 var(--space-lg);
		border-radius: var(--radius-sm);
		background: var(--primary);
		color: white;
		font-size: 14px;
		font-weight: 700;
	}
</style>
