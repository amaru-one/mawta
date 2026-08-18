<script lang="ts">
	import { hapticTap } from '$lib/haptics';
	import type { CourseStatus, HomeCourse } from '$lib/types';
	import Icon from './Icon.svelte';

	interface Props {
		course: HomeCourse;
	}

	let { course }: Props = $props();

	const STATUS_FILL: Record<CourseStatus, string> = {
		live: 'var(--fill-primary)',
		pending: 'var(--fill-warning)',
		idle: 'var(--border)'
	};

	const STATUS_LABEL: Record<CourseStatus, string> = {
		live: 'En curso',
		pending: 'Pendiente',
		idle: 'Sin iniciar'
	};
</script>

<div class="card course">
	<div class="row">
		<span class="icon-tile"><Icon name={course.icon} size={18} /></span>
		<p class="name">{course.name}</p>
		<span class="status" title={STATUS_LABEL[course.status]}>
			<span class="dot" style="background:{STATUS_FILL[course.status]}"></span>
			<span class="sr-only">{STATUS_LABEL[course.status]}</span>
		</span>
	</div>
	<div class="divider"></div>
	<div class="row foot">
		<div class="schedule">
			{#each course.schedule as line (line)}
				<div>{line}</div>
			{/each}
		</div>
		<a class="btn-dark pressable" href="/class/{course.id}" onclick={hapticTap}>Ver clase</a>
	</div>
</div>

<style>
	.course {
		padding: 14px var(--space-lg);
	}

	.name {
		flex: 1;
		margin: 0;
		font-weight: 500;
		font-size: 15px;
	}

	.status {
		width: 32px;
		height: 32px;
		border-radius: var(--radius-md);
		background: var(--surface-1);
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}

	.divider {
		margin: var(--space-md) 0;
	}

	.foot {
		justify-content: space-between;
	}

	.schedule {
		font-size: 13px;
		color: var(--text-secondary);
		line-height: 1.6;
	}

	.foot .btn-dark {
		flex-shrink: 0;
		margin-left: var(--space-md);
		text-decoration: none;
		white-space: nowrap;
	}

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
		white-space: nowrap;
	}
</style>
