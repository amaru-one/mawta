<script lang="ts">
	import { hapticTap } from '$lib/haptics';
	import { gradeFor, trendFor } from '$lib/grades';
	import {
		addNote,
		noteDurations,
		removeNote,
		setAttendance,
		setFlag,
		setParticipation
	} from '$lib/lesson';
	import { assessments, notes, scores } from '$lib/stores';
	import { showToast } from '$lib/toast';
	import type { Attendance, Entry, Note, Participation, Student } from '$lib/types';
	import AttendanceControl from './AttendanceControl.svelte';
	import FlagButton from './FlagButton.svelte';
	import LevelBadge from './LevelBadge.svelte';
	import MicButton from './MicButton.svelte';
	import ParticipationControl from './ParticipationControl.svelte';
	import VoiceNotePlayer from './VoiceNotePlayer.svelte';

	interface Props {
		entry: Entry;
		student: Student;
	}

	let { entry, student }: Props = $props();

	let recordingNow = $state(false);
	let flash = $state(false);

	const rowNotes = $derived($notes.get(entry.id) ?? []);
	const isAbsent = $derived(entry.attendance === 'absent');
	const grade = $derived(gradeFor(student.id, $scores, $assessments));
	const trend = $derived(trendFor(student.id, $scores, $assessments));

	function flashRow(): void {
		flash = true;
		setTimeout(() => (flash = false), 250);
	}

	function handleAttendance(value: Attendance): void {
		hapticTap();
		void setAttendance(student.id, value);
		flashRow();
		showToast(value === 'present' ? 'Marcado presente' : 'Marcado ausente');
	}

	function handleParticipation(value: Participation): void {
		hapticTap();
		void setParticipation(student.id, value);
		showToast('Participación actualizada');
	}

	function handleFlag(value: boolean): void {
		hapticTap();
		setFlag(student.id, value);
		showToast(value ? 'Alumno marcado' : 'Marca retirada');
	}

	function handleRecorded(blob: Blob, durationSec: number): void {
		void addNote(student.id, blob, durationSec);
		showToast('Nota guardada');
	}

	function handleDelete(note: Note): void {
		const undo = removeNote(note);
		showToast('Nota eliminada', { onUndo: undo.restore });
	}

	function handleSave(): void {
		hapticTap();
		showToast('Nota guardada');
	}
</script>

<div class="card student" class:absent={isAbsent} class:recording={recordingNow} class:flash>
	<div class="row head">
		<a class="name" href="/grades/{student.id}" onclick={hapticTap}>
			{student.firstName}
			{student.lastName}
		</a>
		<div class="row marks">
			{#if trend}
				<span class="trend" class:up={trend.direction === 'up'}>{trend.from} →</span>
			{/if}
			<LevelBadge tier={grade.tier} />
			<AttendanceControl value={entry.attendance} onchange={handleAttendance} />
		</div>
	</div>

	<div class="row controls">
		<ParticipationControl
			value={entry.participation}
			disabled={isAbsent}
			onchange={handleParticipation}
		/>
		<FlagButton flagged={entry.flagged} onchange={handleFlag} />
		<MicButton
			hasNotes={rowNotes.length > 0}
			onrecorded={handleRecorded}
			onrecordingchange={(r) => (recordingNow = r)}
			disabled={!entry.attendance}
		/>
	</div>

	{#if rowNotes.length > 0}
		<div class="notes">
			{#each rowNotes as note (note.id)}
				<VoiceNotePlayer
					{note}
					knownDuration={$noteDurations.get(note.id)}
					ondelete={handleDelete}
					onsave={handleSave}
				/>
			{/each}
		</div>
	{/if}
</div>

<style>
	.student {
		padding: 14px var(--space-lg);
		transition:
			background-color 150ms ease-out,
			box-shadow 150ms ease-out;
	}

	.student.absent {
		background: var(--bg-danger);
	}

	.student.recording {
		border-color: var(--border-strong);
	}

	.student.flash {
		box-shadow: var(--shadow-accent);
	}

	.head {
		justify-content: space-between;
		gap: var(--space-sm);
		margin-bottom: var(--space-md);
	}

	.name {
		font-size: 15px;
		font-weight: 500;
		color: inherit;
		text-decoration: none;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.absent .name {
		color: var(--text-secondary);
	}

	.marks {
		gap: var(--space-sm);
		flex-shrink: 0;
	}

	/* A drop in tier is the plain signal; a rise borrows the accent. */
	.trend {
		font-size: 11px;
		color: var(--text-danger);
	}

	.trend.up {
		color: var(--text-accent);
	}

	.controls {
		gap: 14px;
	}

	.notes {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
		margin-top: 10px;
	}
</style>
