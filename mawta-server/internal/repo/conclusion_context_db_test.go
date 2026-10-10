package repo_test

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/dbtest"
	"mawta-server/internal/repo"
)

// The sweep's and the conclusions agent's queries against the real schema:
// a voice note goes from pending to swept, is discarded, confirmed and
// reassigned, and the conclusion context reads only what it should.
func TestVoiceNoteSweepAndConclusionContext(t *testing.T) {
	env := dbtest.Setup(t)
	fx := env.Fx
	student, other := fx.Students[0], fx.Students[1]

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		noteID, err := repo.CreateVoiceNote(ctx, tx, fx.SessionOne, student, fx.ClassMat5B, fx.TeacherQuispe, 4000, []byte("audio"), nil, nil)
		if err != nil {
			t.Fatalf("CreateVoiceNote: %v", err)
		}
		if err := repo.SetVoiceNoteTranscript(ctx, tx, noteID, "Hoy Pedro ayudó a Ana con las fracciones."); err != nil {
			t.Fatalf("SetVoiceNoteTranscript: %v", err)
		}

		var termID uuid.UUID
		if err := tx.QueryRow(ctx, `select term_id from class_sessions where id = $1`, fx.SessionOne).Scan(&termID); err != nil {
			t.Fatalf("session term: %v", err)
		}

		pending, err := repo.PendingVoiceNotesForStudentTerm(ctx, tx, fx.ClassMat5B, student, termID)
		if err != nil || len(pending) != 1 || pending[0] != noteID {
			t.Fatalf("pending = %v, %v; want the new note", pending, err)
		}
		note, err := repo.GetVoiceNoteForRedaction(ctx, tx, noteID)
		if err != nil || note.Transcript == nil || note.AttributionStatus != repo.AttributionPending {
			t.Fatalf("GetVoiceNoteForRedaction = %+v, %v", note, err)
		}
		names, err := repo.StudentNames(ctx, tx, []uuid.UUID{student, other})
		if err != nil || len(names) != 2 {
			t.Fatalf("StudentNames = %v, %v", names, err)
		}

		// A sweep generation and its rows: the note named only a classmate.
		sid, vid := student, noteID
		gen, created, err := repo.CreateGeneration(ctx, tx, repo.NewGeneration{
			Agent: "redaction", Kind: "voice_note", ClassID: fx.ClassMat5B, StudentID: &sid, VoiceNoteID: &vid,
			RequestedBy: fx.TeacherQuispe, TargetKey: "test:redaction", Deadline: time.Minute,
		})
		if err != nil || !created {
			t.Fatalf("CreateGeneration(redaction) = %v, %v", created, err)
		}
		matched := other
		if err := repo.InsertVoiceNoteRedaction(ctx, tx, repo.VoiceNoteRedaction{
			VoiceNoteID: noteID, GenerationID: gen.ID, StudentID: student, OriginalText: "Pedro",
			StartOffset: 4, EndOffset: 9, Replacement: "[COMPAÑERO_1]", RefersTo: repo.RefersToClassmate,
			MatchedStudentID: &matched,
		}); err != nil {
			t.Fatalf("InsertVoiceNoteRedaction: %v", err)
		}
		redacted := "Hoy [COMPAÑERO_1] ayudó a [PERSONA] con las fracciones."
		reason := repo.DiscardMentionsOtherStudent
		if err := repo.SetVoiceNoteAttribution(ctx, tx, noteID, &redacted, repo.AttributionDiscarded, &reason); err != nil {
			t.Fatalf("SetVoiceNoteAttribution: %v", err)
		}

		usable, counts, err := repo.ListConclusionVoiceNotes(ctx, tx, fx.ClassMat5B, student, termID)
		if err != nil || len(usable) != 0 || counts.Discarded != 1 {
			t.Fatalf("ListConclusionVoiceNotes = %v, %+v, %v; want only a discarded count", usable, counts, err)
		}
		discarded, err := repo.ListDiscardedVoiceNotes(ctx, tx, fx.ClassMat5B, student, termID)
		if err != nil || len(discarded) != 1 || discarded[0].DiscardReason != reason {
			t.Fatalf("ListDiscardedVoiceNotes = %+v, %v", discarded, err)
		}

		if err := repo.ConfirmVoiceNote(ctx, tx, noteID); err != nil {
			t.Fatalf("ConfirmVoiceNote: %v", err)
		}
		usable, counts, err = repo.ListConclusionVoiceNotes(ctx, tx, fx.ClassMat5B, student, termID)
		if err != nil || len(usable) != 1 || usable[0].TranscriptRedacted != redacted || counts.Discarded != 0 {
			t.Fatalf("after confirm: %v, %+v, %v; want the redacted note", usable, counts, err)
		}
		if err := repo.ConfirmVoiceNote(ctx, tx, noteID); err == nil {
			t.Fatal("confirming a usable note must be refused")
		}

		if err := repo.ReassignVoiceNote(ctx, tx, noteID, other); err != nil {
			t.Fatalf("ReassignVoiceNote: %v", err)
		}
		var live int
		if err := tx.QueryRow(ctx, `select count(*) from voice_note_redactions where voice_note_id = $1 and superseded_at is null`, noteID).Scan(&live); err != nil || live != 0 {
			t.Fatalf("live redaction rows after reassign = %d, %v; want 0", live, err)
		}
		if pending, _ := repo.PendingVoiceNotesForStudentTerm(ctx, tx, fx.ClassMat5B, other, termID); len(pending) != 1 {
			t.Fatalf("the reassigned note must be pending for its new student, got %v", pending)
		}

		// The conclusion context queries.
		if ok, err := repo.CompetencyInClass(ctx, tx, fx.ClassMat5B, fx.CompetencyC2); err != nil || !ok {
			t.Fatalf("CompetencyInClass = %v, %v", ok, err)
		}
		if lvl, err := repo.LiveCompetencyLevel(ctx, tx, student, fx.CompetencyC2, termID); err != nil || lvl != nil {
			t.Fatalf("LiveCompetencyLevel = %v, %v; want none yet", lvl, err)
		}
		if _, err := repo.AssertCompetencyLevel(ctx, tx, fx.ClassMat5B, student, fx.CompetencyC2, termID, fx.TeacherQuispe, "B", nil); err != nil {
			t.Fatalf("AssertCompetencyLevel: %v", err)
		}
		if lvl, err := repo.LiveCompetencyLevel(ctx, tx, student, fx.CompetencyC2, termID); err != nil || lvl == nil || *lvl != "B" {
			t.Fatalf("LiveCompetencyLevel = %v, %v; want B", lvl, err)
		}
		if _, err := repo.ConclusionRequirement(ctx, tx, fx.ClassMat5B, student, fx.CompetencyC2, termID); err != nil {
			t.Fatalf("ConclusionRequirement: %v", err)
		}
		if c, err := repo.GetCompetencyBrief(ctx, tx, fx.CompetencyC2); err != nil || c.Name == "" {
			t.Fatalf("GetCompetencyBrief = %+v, %v", c, err)
		}
		if _, err := repo.ListConclusionEvidence(ctx, tx, fx.ClassMat5B, student, fx.CompetencyC2, termID); err != nil {
			t.Fatalf("ListConclusionEvidence: %v", err)
		}
		if _, err := repo.ListEarlierTermConclusions(ctx, tx, student, fx.CompetencyC2, termID); err != nil {
			t.Fatalf("ListEarlierTermConclusions: %v", err)
		}
		if names, err := repo.RosterNames(ctx, tx, fx.ClassMat5B, student, time.Now()); err != nil || len(names) == 0 {
			t.Fatalf("RosterNames = %v, %v", names, err)
		}

		// A conclusions generation must carry its scope, and a saved
		// conclusion may point at it.
		cid, tid := fx.CompetencyC2, termID
		concl, _, err := repo.CreateGeneration(ctx, tx, repo.NewGeneration{
			Agent: "conclusions", Kind: "conclusion", ClassID: fx.ClassMat5B,
			StudentID: &sid, CompetencyID: &cid, TermID: &tid,
			RequestedBy: fx.TeacherQuispe, TargetKey: "test:conclusion", Deadline: time.Minute,
		})
		if err != nil {
			t.Fatalf("CreateGeneration(conclusions): %v", err)
		}
		latest, ok, err := repo.LatestConclusionGeneration(ctx, tx, student, fx.CompetencyC2, termID)
		if err != nil || !ok || latest.ID != concl.ID {
			t.Fatalf("LatestConclusionGeneration = %v, %v, %v", latest.ID, ok, err)
		}
		if _, err := repo.UpsertConclusion(ctx, tx, fx.ClassMat5B, student, fx.CompetencyC2, termID, fx.TeacherQuispe,
			"Texto.", "draft", &concl.ID); err == nil {
			t.Fatal("a pending generation must not be accepted as the source of a conclusion")
		}
		if err := repo.CompleteGeneration(ctx, tx, concl.ID, json.RawMessage(`{"body":"x"}`), repo.Usage{}); err != nil {
			t.Fatalf("CompleteGeneration: %v", err)
		}
		if _, err := repo.UpsertConclusion(ctx, tx, fx.ClassMat5B, student, fx.CompetencyC2, termID, fx.TeacherQuispe,
			"Texto.", "draft", &concl.ID); err != nil {
			t.Fatalf("UpsertConclusion with generation: %v", err)
		}
	})
}
