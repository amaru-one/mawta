<script lang="ts">
	import { hapticTap } from '$lib/haptics';
	import { currentCourse, currentSession } from '$lib/stores';

	const dateLabel = $derived(
		$currentSession
			? new Date($currentSession.date).toLocaleDateString('en-GB', {
					weekday: 'short',
					day: 'numeric',
					month: 'short'
				})
			: ''
	);

	const lessonTopic = $derived(
		$currentSession?.blocks.find((b) => b.kind === 'lesson')?.topic ?? 'fractions'
	);
</script>

<header class="header">
	<div class="title-line">
		<h1>{$currentCourse?.name ?? ''}</h1>
		<span class="when">
			{dateLabel} {$currentSession?.startTime}–{$currentSession?.endTime}
		</span>
	</div>
	<p class="plan">Lesson: {lessonTopic}</p>
</header>

<style>
	.header {
		padding: var(--space-sm) 0 var(--space-lg);
	}

	.title-line {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
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
		margin: var(--space-xs) 0 0;
		font-size: 14px;
		color: var(--neutral-600);
	}
</style>
