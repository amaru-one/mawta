<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { hapticTap } from '$lib/haptics';
	import { gradeFor, loadScoresForStudent, saveScore } from '$lib/grades';
	import { loadToday } from '$lib/lesson';
	import { assessments, scores, students } from '$lib/stores';
	import { showToast } from '$lib/toast';

	let ready = $state(false);

	onMount(() => {
		const studentId = page.params.studentId;
		void Promise.all([
			loadToday(),
			studentId ? loadScoresForStudent(studentId) : Promise.resolve()
		]).then(() => {
			ready = true;
		});
	});

	const student = $derived($students.find((s) => s.id === page.params.studentId) ?? null);
	const grade = $derived(student ? gradeFor(student.id, $scores, $assessments) : null);

	function handleScoreChange(componentId: string, maxValue: number, e: Event): void {
		if (!student) return;
		const target = e.currentTarget as HTMLInputElement;
		const parsed = Number(target.value);
		if (!Number.isFinite(parsed)) return;
		const clamped = Math.min(maxValue, Math.max(0, Math.round(parsed)));
		target.value = String(clamped);
		hapticTap();
		saveScore(student.id, componentId, clamped);
		showToast('Score saved');
	}
</script>

<svelte:head>
	<title>{student ? `${student.firstName} ${student.lastName}` : 'Grades'}</title>
</svelte:head>

<main class="screen">
	<a class="back" href="/">← Back to roster</a>

	{#if ready}
		{#if student && grade}
			<div class="page-header">
				<h1>{student.firstName} {student.lastName}</h1>
				<p class="subtitle">Enter each component's score — unscored ones show sample data.</p>
			</div>

			<div class="summary">
				<span class="grade-badge" class:low={grade.percent < 70}>
					{grade.letter} · {grade.percent}%
				</span>
			</div>

			<ul class="component-list">
				{#each grade.components as c (c.component.id)}
					<li class="component-row">
						<span class="label">{c.component.label}</span>
						<span class="weight">{c.component.weight}%</span>
						<span class="input-wrap">
							<input
								type="number"
								class="score-input"
								min="0"
								max={c.maxValue}
								value={c.rawValue}
								onchange={(e) => handleScoreChange(c.component.id, c.maxValue, e)}
								aria-label={`${c.component.label} score, out of ${c.maxValue}`}
							/>
							<span class="max">/ {c.maxValue}</span>
						</span>
						<span class="score">{c.score}%</span>
					</li>
				{/each}
			</ul>
		{:else}
			<p class="empty">Student not found.</p>
		{/if}
	{/if}
</main>

<style>
	.screen {
		max-width: 1200px;
		margin: 0 auto;
		padding: var(--space-lg) var(--space-lg) var(--space-3xl);
	}

	.back {
		display: inline-block;
		margin-bottom: var(--space-lg);
		font-size: 14px;
		font-weight: 600;
		color: var(--neutral-600);
		text-decoration: none;
	}

	.back:hover {
		color: var(--black);
	}

	.page-header {
		margin-bottom: var(--space-lg);
	}

	h1 {
		margin: 0;
		font-size: 24px;
		line-height: 32px;
		font-weight: 700;
		letter-spacing: 0.3px;
	}

	.subtitle {
		margin: var(--space-xs) 0 0;
		font-size: 14px;
		color: var(--neutral-600);
	}

	.summary {
		margin-bottom: var(--space-lg);
	}

	.grade-badge {
		display: inline-block;
		font-family: var(--font-mono);
		font-size: 16px;
		font-weight: 700;
		color: var(--neutral-900);
		background: var(--gray-100);
		padding: 6px 14px;
		border-radius: var(--radius-sm);
	}

	.grade-badge.low {
		background: var(--black);
		color: var(--white);
	}

	.component-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.component-row {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		padding: var(--space-md) var(--space-lg);
		background: var(--white);
		border: 1px solid var(--gray-200);
		border-radius: var(--radius-md);
	}

	.label {
		font-size: 15px;
		font-weight: 600;
		flex: 1;
	}

	.weight {
		font-size: 13px;
		color: var(--neutral-600);
	}

	.input-wrap {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}

	.score-input {
		width: 56px;
		font-family: var(--font-mono);
		font-size: 13px;
		font-weight: 700;
		color: var(--neutral-900);
		background: var(--gray-50);
		border: 1px solid var(--gray-300);
		border-radius: var(--radius-sm);
		padding: 4px 6px;
		text-align: right;
	}

	.score-input:focus {
		outline: none;
		border-color: var(--black);
	}

	.max {
		font-size: 13px;
		color: var(--neutral-600);
	}

	.score {
		font-family: var(--font-mono);
		font-size: 13px;
		font-weight: 700;
		color: var(--neutral-900);
		background: var(--gray-100);
		padding: 4px 10px;
		border-radius: var(--radius-sm);
		min-width: 44px;
		text-align: center;
	}

	.empty {
		color: var(--neutral-600);
		font-size: 14px;
	}

	@media (min-width: 768px) {
		.screen {
			padding: var(--space-lg) var(--space-xl) var(--space-3xl);
		}
	}
</style>
