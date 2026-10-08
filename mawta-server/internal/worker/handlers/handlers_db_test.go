package handlers_test

import (
	"context"
	"errors"
	"fmt"
	"os"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/db"
	"mawta-server/internal/dbtest"
	"mawta-server/internal/stt"
	"mawta-server/internal/worker/handlers"
)

func TestMain(m *testing.M) { os.Exit(dbtest.Main(m)) }

// inTx runs fn in a tenant transaction that is always rolled back, so each
// test sees the pristine fixture.
func inTx(t *testing.T, env *dbtest.Env, fn func(ctx context.Context, tx pgx.Tx)) {
	t.Helper()
	ctx := context.Background()

	tx, err := env.App.Pool.Begin(ctx)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	defer tx.Rollback(ctx) //nolint:errcheck

	if _, err := tx.Exec(ctx, "set local role mawta_app"); err != nil {
		t.Fatalf("set role: %v", err)
	}
	// A job runs with a tenant but no actor — actor_type 'job'.
	if _, err := tx.Exec(ctx,
		`select set_config('app.tenant_id', $1, true),
		        set_config('app.actor_id', '', true),
		        set_config('app.request_id', 'job:test', true)`,
		env.Fx.TenantA.String()); err != nil {
		t.Fatalf("set tenant context: %v", err)
	}

	fn(ctx, tx)
}

// ------------------------------------------------------------ transcription --

// The reachable branch, per the decision to keep internal/stt without a
// provider interface: an empty API key is a permanent failure. The handler
// must record it on the domain row and return nil, because returning an error
// would burn up to 20 retries — each a real, possibly billable provider
// call — against something retrying can never fix.
//
// The success and transient-retry branches stay untested: they need a seam
// internal/stt/SPEC.md deliberately does not provide. Recorded there as an
// open question rather than left invisible.
func TestTranscriptionPermanentFailureIsRecordedNotRetried(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		var voiceNoteID uuid.UUID
		if err := tx.QueryRow(ctx, `
			insert into voice_notes (tenant_id, session_id, student_id, class_id, teacher_id, duration_ms, audio, mime_type, byte_size)
			values (app.current_tenant_id(), $1, $2, $3, $4, 5000, $5, 'audio/mpeg', 4)
			returning id`,
			env.Fx.SessionOne, env.Fx.Students[0], env.Fx.ClassMat5B, env.Fx.TeacherQuispe, []byte("fake")).Scan(&voiceNoteID); err != nil {
			t.Fatalf("insert a voice note: %v", err)
		}

		// No API key: stt.Client fails permanently on first use.
		transcribe := handlers.VoiceNoteTranscribe(stt.NewClient("", ""))
		payload := []byte(fmt.Sprintf(`{"voice_note_id":%q}`, voiceNoteID))

		if err := transcribe(ctx, tx, 1, payload); err != nil {
			t.Fatalf("a permanent failure must not be returned as a job error (it would burn 20 retries): %v", err)
		}

		var status string
		var transcript *string
		if err := tx.QueryRow(ctx,
			`select transcription_status, transcript from voice_notes where id = $1`, voiceNoteID).
			Scan(&status, &transcript); err != nil {
			t.Fatalf("read: %v", err)
		}
		if status != "failed" {
			t.Errorf("transcription_status = %q, want failed", status)
		}
		if transcript != nil {
			t.Errorf("transcript = %q, want null on a failure", *transcript)
		}
	})
}

// A note discarded before its job ran is a no-op, not an error: the work is
// moot, and failing would retry it twenty times.
func TestTranscribingADiscardedNoteIsANoOp(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		transcribe := handlers.VoiceNoteTranscribe(stt.NewClient("", ""))
		payload := []byte(fmt.Sprintf(`{"voice_note_id":%q}`, uuid.New()))

		if err := transcribe(ctx, tx, 1, payload); err != nil {
			t.Errorf("a missing voice note should be a no-op, got: %v", err)
		}
	})
}

// ----------------------------------------------- voice note + enqueue, atomic --

// The enqueue rides the same transaction as the insert, so there is never a
// voice note with no transcription job or a job for a note that was rolled
// back.
func TestVoiceNoteAndItsJobCommitTogether(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()

	tc := db.TenantCtx{TenantID: env.Fx.TenantA, TeacherID: env.Fx.TeacherQuispe, RequestID: "test"}

	var voiceNoteID uuid.UUID
	err := env.App.WithTenantTx(ctx, tc, func(tx pgx.Tx) error {
		if err := tx.QueryRow(ctx, `
			insert into voice_notes (tenant_id, session_id, student_id, class_id, teacher_id, duration_ms, audio)
			values (app.current_tenant_id(), $1, $2, $3, $4, 5000, $5) returning id`,
			env.Fx.SessionOne, env.Fx.Students[0], env.Fx.ClassMat5B, env.Fx.TeacherQuispe, []byte("fake")).Scan(&voiceNoteID); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
			insert into jobs (tenant_id, kind, queue, priority, payload, unique_key)
			values ($1, 'voice_note.transcribe', 'default', 3, $2, $3)`,
			env.Fx.TenantA,
			[]byte(fmt.Sprintf(`{"voice_note_id":%q}`, voiceNoteID)),
			"voice_note.transcribe:"+voiceNoteID.String()); err != nil {
			return err
		}
		// Fail after both writes: neither may survive.
		return fmt.Errorf("simulated failure after the note and its job were written")
	})
	if err == nil {
		t.Fatal("expected the transaction to fail")
	}

	var notes, jobs int
	if err := env.Admin.Pool.QueryRow(ctx,
		`select (select count(*) from voice_notes where id = $1),
		        (select count(*) from jobs where unique_key = $2)`,
		voiceNoteID, "voice_note.transcribe:"+voiceNoteID.String()).Scan(&notes, &jobs); err != nil {
		t.Fatalf("count: %v", err)
	}
	if notes != 0 || jobs != 0 {
		t.Errorf("after a rolled-back transaction: %d voice note(s), %d job(s); want 0 and 0", notes, jobs)
	}
}

// TestTranscriptionSuccess verifies that when the transcriber returns a successful
// transcript, the handler saves it and marks the status as completed.
func TestTranscriptionSuccess(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		var voiceNoteID uuid.UUID
		if err := tx.QueryRow(ctx, `
			insert into voice_notes (tenant_id, session_id, student_id, class_id, teacher_id, duration_ms, audio, mime_type, byte_size)
			values (app.current_tenant_id(), $1, $2, $3, $4, 5000, $5, 'audio/mpeg', 4)
			returning id`,
			env.Fx.SessionOne, env.Fx.Students[0], env.Fx.ClassMat5B, env.Fx.TeacherQuispe, []byte("fake")).Scan(&voiceNoteID); err != nil {
			t.Fatalf("insert a voice note: %v", err)
		}

		// Mock transcriber that returns a successful transcript
		mockTranscriber := &mockTranscriber{
			transcript: "prueba de transcripción",
			err:        nil,
		}
		transcribe := handlers.VoiceNoteTranscribe(mockTranscriber)
		payload := []byte(fmt.Sprintf(`{"voice_note_id":%q}`, voiceNoteID))

		if err := transcribe(ctx, tx, 1, payload); err != nil {
			t.Fatalf("transcription success should not return an error: %v", err)
		}

		var status string
		var transcript *string
		if err := tx.QueryRow(ctx,
			`select transcription_status, transcript from voice_notes where id = $1`, voiceNoteID).
			Scan(&status, &transcript); err != nil {
			t.Fatalf("read: %v", err)
		}
		if status != "completed" {
			t.Errorf("transcription_status = %q, want completed", status)
		}
		if transcript == nil || *transcript != "prueba de transcripción" {
			t.Errorf("transcript = %v, want 'prueba de transcripción'", transcript)
		}
	})
}

// TestTranscriptionTransientError verifies that when the transcriber returns a
// transient error (not wrapping stt.ErrPermanent), the handler propagates the error
// and does not mark the note as failed.
func TestTranscriptionTransientError(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		var voiceNoteID uuid.UUID
		if err := tx.QueryRow(ctx, `
			insert into voice_notes (tenant_id, session_id, student_id, class_id, teacher_id, duration_ms, audio, mime_type, byte_size)
			values (app.current_tenant_id(), $1, $2, $3, $4, 5000, $5, 'audio/mpeg', 4)
			returning id`,
			env.Fx.SessionOne, env.Fx.Students[0], env.Fx.ClassMat5B, env.Fx.TeacherQuispe, []byte("fake")).Scan(&voiceNoteID); err != nil {
			t.Fatalf("insert a voice note: %v", err)
		}

		// Mock transcriber that returns a transient error
		expectedErr := errors.New("network timeout")
		mockTranscriber := &mockTranscriber{
			transcript: "",
			err:        expectedErr,
		}
		transcribe := handlers.VoiceNoteTranscribe(mockTranscriber)
		payload := []byte(fmt.Sprintf(`{"voice_note_id":%q}`, voiceNoteID))

		err := transcribe(ctx, tx, 1, payload)
		if err == nil {
			t.Fatalf("transient error should be propagated")
		}
		if !errors.Is(err, expectedErr) {
			t.Errorf("handler returned %v, want an error that wraps the transient error", err)
		}

		var status string
		var transcript *string
		if err := tx.QueryRow(ctx,
			`select transcription_status, transcript from voice_notes where id = $1`, voiceNoteID).
			Scan(&status, &transcript); err != nil {
			t.Fatalf("read: %v", err)
		}
		if status != "pending" {
			t.Errorf("transcription_status = %q, want pending (should not be marked as failed for transient error)", status)
		}
		if transcript != nil {
			t.Errorf("transcript = %v, want null for transient error", transcript)
		}
	})
}

// mockTranscriber implements the Transcriber interface for testing purposes.
type mockTranscriber struct {
	transcript string
	err        error
}

func (m *mockTranscriber) Transcribe(ctx context.Context, audioMP3 []byte) (string, error) {
	return m.transcript, m.err
}
