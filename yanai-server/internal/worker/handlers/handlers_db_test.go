package handlers_test

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/db"
	"yanai-server/internal/dbtest"
	"yanai-server/internal/stt"
	"yanai-server/internal/worker/handlers"
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

	if _, err := tx.Exec(ctx, "set local role yanai_app"); err != nil {
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

// --------------------------------------------------------- grade recompute --

// The rule the whole architecture is arranged around: the worker computes the
// school's optional internal number and must never touch the official MINEDU
// record. There is no constraint stopping it — only this.
func TestGradeRecomputeNeverTouchesTheOfficialRecord(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		// A teacher's judgement already on record.
		var levelID uuid.UUID
		if err := tx.QueryRow(ctx, `
			insert into competency_term_levels
			  (tenant_id, student_id, competency_id, academic_year_id, term_id, class_id, scale_level_id, asserted_by_id)
			values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7) returning id`,
			env.Fx.Students[0], env.Fx.CompetencyC2, env.Fx.YearA, env.Fx.TermII,
			env.Fx.ClassMat5B, env.Fx.LevelB, env.Fx.TeacherQuispe).Scan(&levelID); err != nil {
			t.Fatalf("assert a level: %v", err)
		}

		var before, after int
		if err := tx.QueryRow(ctx, `select count(*) from competency_term_levels`).Scan(&before); err != nil {
			t.Fatalf("count: %v", err)
		}

		payload, _ := json.Marshal(map[string]string{
			"class_id": env.Fx.ClassMat5B.String(),
			"term_id":  env.Fx.TermII.String(),
		})
		if err := handlers.GradeRecompute(ctx, tx, 1, payload); err != nil {
			t.Fatalf("GradeRecompute: %v", err)
		}

		if err := tx.QueryRow(ctx, `select count(*) from competency_term_levels`).Scan(&after); err != nil {
			t.Fatalf("count: %v", err)
		}
		if after != before {
			t.Errorf("competency_term_levels went from %d to %d rows; a job must never write the official record", before, after)
		}

		// The asserted level is untouched — not superseded, not re-pointed.
		var scaleLevel uuid.UUID
		var supersededAt *string
		if err := tx.QueryRow(ctx,
			`select scale_level_id, superseded_at::text from competency_term_levels where id = $1`, levelID).
			Scan(&scaleLevel, &supersededAt); err != nil {
			t.Fatalf("read the level: %v", err)
		}
		if scaleLevel != env.Fx.LevelB || supersededAt != nil {
			t.Error("the recompute altered a teacher's asserted nivel de logro")
		}
	})
}

func TestGradeRecomputeWritesTheInternalGrade(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		payload, _ := json.Marshal(map[string]string{
			"class_id":   env.Fx.ClassMat5B.String(),
			"term_id":    env.Fx.TermII.String(),
			"student_id": env.Fx.Students[0].String(),
		})
		if err := handlers.GradeRecompute(ctx, tx, 1, payload); err != nil {
			t.Fatalf("GradeRecompute: %v", err)
		}

		// The fixture has one score, 16/20, in a single component weighted 1.
		var normalized float64
		var scope string
		if err := tx.QueryRow(ctx, `
			select normalized_value, scope from computed_grades
			 where student_id = $1 and class_id = $2 and term_id = $3
			   and superseded_at is null and deleted_at is null`,
			env.Fx.Students[0], env.Fx.ClassMat5B, env.Fx.TermII).Scan(&normalized, &scope); err != nil {
			t.Fatalf("read the computed grade: %v", err)
		}
		if normalized < 0.79 || normalized > 0.81 {
			t.Errorf("normalized_value = %v, want ~0.80 (16 of 20)", normalized)
		}
		if scope != "term_partial" {
			t.Errorf("scope = %q, want term_partial — nothing here produces a final grade", scope)
		}

		var components int
		if err := tx.QueryRow(ctx, `
			select count(*) from computed_grade_components cgc
			  join computed_grades cg on cg.id = cgc.computed_grade_id
			 where cg.student_id = $1 and cg.superseded_at is null`, env.Fx.Students[0]).Scan(&components); err != nil {
			t.Fatalf("count components: %v", err)
		}
		if components != 1 {
			t.Errorf("computed_grade_components = %d, want 1", components)
		}
	})
}

// The inputs_digest short-circuit: recomputing unchanged inputs must not churn
// a new row, or every score write in a class would supersede everyone's grade.
func TestGradeRecomputeIsIdempotentOnUnchangedInputs(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		payload, _ := json.Marshal(map[string]string{
			"class_id":   env.Fx.ClassMat5B.String(),
			"term_id":    env.Fx.TermII.String(),
			"student_id": env.Fx.Students[0].String(),
		})
		for i := 0; i < 3; i++ {
			if err := handlers.GradeRecompute(ctx, tx, int64(i+1), payload); err != nil {
				t.Fatalf("GradeRecompute %d: %v", i, err)
			}
		}

		var total int
		if err := tx.QueryRow(ctx,
			`select count(*) from computed_grades where student_id = $1`, env.Fx.Students[0]).Scan(&total); err != nil {
			t.Fatalf("count: %v", err)
		}
		if total != 1 {
			t.Errorf("computed_grades rows = %d after three identical recomputes, want 1", total)
		}
	})
}

// A student with no scores has no grade — not a zero. A zero would be a
// failing mark nobody awarded.
func TestGradeRecomputeSkipsAStudentWithNoScores(t *testing.T) {
	env := dbtest.Setup(t)

	inTx(t, env, func(ctx context.Context, tx pgx.Tx) {
		payload, _ := json.Marshal(map[string]string{
			"class_id":   env.Fx.ClassMat5B.String(),
			"term_id":    env.Fx.TermII.String(),
			"student_id": env.Fx.Students[3].String(), // never scored
		})
		if err := handlers.GradeRecompute(ctx, tx, 1, payload); err != nil {
			t.Fatalf("GradeRecompute: %v", err)
		}

		var n int
		if err := tx.QueryRow(ctx,
			`select count(*) from computed_grades where student_id = $1`, env.Fx.Students[3]).Scan(&n); err != nil {
			t.Fatalf("count: %v", err)
		}
		if n != 0 {
			t.Errorf("computed_grades rows = %d for an unscored student, want 0", n)
		}
	})
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
