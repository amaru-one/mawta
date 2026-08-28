<script lang="ts">
	import type { Tier } from '$lib/grades';
	import type { CriterionDto } from '$lib/api/dto';
	import LevelPicker from './LevelPicker.svelte';

	interface Props {
		criterion: CriterionDto;
		onLevelChange: (criterionId: string, level: Tier) => Promise<void>;
	}

	let { criterion, onLevelChange }: Props = $props();

	let saving = $state(false);

	async function selectLevel(level: Tier): Promise<void> {
		if (saving) return;
		saving = true;
		try {
			await onLevelChange(criterion.criterion_id, level);
		} finally {
			saving = false;
		}
	}
</script>

<div class="criterion">
	<p class="text">{criterion.description}</p>
	<LevelPicker level={criterion.level} disabled={saving} size={26} onselect={selectLevel} />
</div>

<style>
	.criterion {
		padding: var(--space-sm) 0;
		border-top: 0.5px solid var(--border-subtle, var(--border-strong));
	}

	.text {
		margin: 0 0 8px;
		font-size: 13px;
		line-height: 1.35;
		color: var(--text-primary);
	}
</style>
