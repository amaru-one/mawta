<script lang="ts">
	import { hapticTap } from '$lib/haptics';
	import { addNote, noteDurations, removeNote, setAttendance, setParticipation } from '$lib/lesson';
	import { notes } from '$lib/stores';
	import { showToast } from '$lib/toast';
	import type { Attendance, Entry, Note, Participation, Student } from '$lib/types';
	import AttendanceControl from './AttendanceControl.svelte';
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

	function flashRow(): void {
		flash = true;
		setTimeout(() => (flash = false), 250);
	}

	function handleAttendance(value: Attendance): void {
		hapticTap();
		void setAttendance(student.id, value);
		flashRow();
		showToast(value === 'present' ? 'Marked present' : 'Marked absent');
	}

	function handleParticipation(value: Participation): void {
		hapticTap();
		void setParticipation(student.id, value);
		showToast('Participation updated');
	}

	function handleRecorded(blob: Blob, durationSec: number): void {
		void addNote(student.id, blob, durationSec);
		showToast('Note saved');
	}

	function handleDelete(note: Note): void {
		const undo = removeNote(note);
		showToast('Note deleted', { onUndo: undo.restore });
	}

	function handleSave(note: Note): void {
		hapticTap();
		showToast('Note saved');
	}
</script>

<div
	class="row"
	class:absent={isAbsent}
	class:has-notes={rowNotes.length > 0}
	class:recording={recordingNow}
	class:flash
>
	<div class="main">
		<a class="student-card" href="/grades/{student.id}" onclick={hapticTap}>
			<div class="who">
				<span class="name">{student.firstName} {student.lastName}</span>
			</div>
		</a>
		<div class="attendance-slot">
			<AttendanceControl value={entry.attendance} onchange={handleAttendance} />
		</div>

		<div class="controls">
			<ParticipationControl
				value={entry.participation}
				disabled={isAbsent}
				onchange={handleParticipation}
			/>
			<MicButton
				hasNotes={rowNotes.length > 0}
				onrecorded={handleRecorded}
				onrecordingchange={(r) => (recordingNow = r)}
				disabled={!entry.attendance}
			/>
		</div>
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
	.row {
		background: var(--neutral-50);
		border-radius: var(--radius-md);
		padding: var(--space-sm) var(--space-lg);
		border-left: 3px solid transparent;
		transition:
			background-color 150ms ease-out,
			border-color 150ms ease-out,
			box-shadow 150ms ease-out;
	}

	.row:hover {
		box-shadow: var(--shadow-sm);
	}

	.row.has-notes {
		border-left-color: var(--primary-light);
	}

	.row.recording {
		border-left-color: var(--primary);
	}

	.row.absent {
		background: var(--action-delete-light);
		border-left-color: var(--action-delete);
	}

	.row.flash {
		box-shadow: var(--shadow-primary);
	}

	.main {
		display: flex;
		align-items: center;
		gap: var(--space-md);
		min-height: 56px;
	}

	.student-card {
		display: flex;
		flex: 1;
		min-width: 0;
		padding: var(--space-xs) var(--space-sm);
		margin: calc(-1 * var(--space-xs)) calc(-1 * var(--space-sm));
		border-radius: var(--radius-md);
		color: inherit;
		text-decoration: none;
		transition: background-color 150ms ease-out;
	}

	.student-card:hover {
		background: var(--neutral-200);
	}

	.absent .student-card:hover {
		background: var(--gray-300);
	}

	.who {
		display: flex;
		flex-direction: column;
		min-width: 0;
		flex: 1;
	}

	.name {
		font-size: 16px;
		font-weight: 500;
		line-height: 24px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.absent .name {
		color: var(--neutral-600);
	}

	.attendance-slot {
		flex-shrink: 0;
	}

	.controls {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-md);
		flex: 1;
		min-width: 120px;
	}

	.notes {
		display: flex;
		flex-direction: column;
		gap: var(--space-xs);
		padding: var(--space-xs) 0 var(--space-sm) calc(36px + var(--space-md));
	}

	@media (max-width: 480px) {
		.row {
			padding: var(--space-sm) var(--space-md);
		}

		.main {
			flex-wrap: wrap;
			row-gap: var(--space-xs);
		}

		.student-card {
			flex: 1 1 40%;
		}

		.controls {
			gap: var(--space-sm);
		}

		.notes {
			padding-left: var(--space-sm);
		}
	}

	@media (max-width: 900px) {
		.name {
			font-size: 16px;
		}
	}

	@media (min-width: 901px) {
		.name {
			font-size: 14px;
			line-height: 20px;
		}
	}
</style>
