package repo

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// plannedEvidenceKinds maps planned_evidences.kind to assessments.kind.
var plannedEvidenceKinds = map[string]string{
	"produccion":     "proyecto",
	"actuacion":      "exposicion",
	"prueba_escrita": "examen",
}

// SyncClassPlan runs SyncExperience for every planned experience of a class.
// It is idempotent, so screens that show the class calendar or the plan call
// it to bring experiences planned before the bridge existed up to date.
func SyncClassPlan(ctx context.Context, tx pgx.Tx, classID uuid.UUID) error {
	rows, err := tx.Query(ctx, `
		select id from learning_experiences
		 where class_id = $1 and status = 'planificada' and deleted_at is null
	`, classID)
	if err != nil {
		return err
	}
	var ids []uuid.UUID
	for rows.Next() {
		var id uuid.UUID
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		ids = append(ids, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for _, id := range ids {
		if err := SyncExperience(ctx, tx, id); err != nil {
			return err
		}
	}
	return nil
}

// SyncExperience makes a planned experience real:
//
//   - each accepted session outline entry names the class session(s) of its
//     date (class_sessions.topic), which is what the class calendar shows;
//   - each accepted planned evidence becomes an assessment tagged with its
//     criteria, so it reaches every student on the roster and can be
//     evaluated. It is valued the way the planned evidence says (numeric out
//     of its max_score, or an AD/A/B/C level). It is linked to the class
//     session of its date, which is also its due date.
//
// A draft experience is left alone. Pending proposals are not synced until the
// teacher accepts them. The function only writes what differs, so calling it
// again is cheap.
func SyncExperience(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID) error {
	var classID, termID uuid.UUID
	var status string
	err := tx.QueryRow(ctx, `
		select class_id, term_id, status from learning_experiences
		 where id = $1 and deleted_at is null
	`, experienceID).Scan(&classID, &termID, &status)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil
	}
	if err != nil {
		return err
	}
	if status != "planificada" {
		return nil
	}

	if _, err := tx.Exec(ctx, `
		update class_sessions cs set topic = e.title
		  from session_outline_entries e
		 where e.experience_id = $1 and e.deleted_at is null and e.accepted_at is not null
		   and cs.class_id = $2 and cs.session_date = e.class_date
		   and cs.deleted_at is null and cs.status <> 'cancelled'
		   and cs.topic is distinct from e.title
	`, experienceID, classID); err != nil {
		return err
	}

	// Evidence that left the plan leaves the students' screens too. Scores
	// already recorded stay in the history, as with any deleted assessment.
	if _, err := tx.Exec(ctx, `
		update assessments set deleted_at = now()
		 where deleted_at is null
		   and planned_evidence_id in (
		     select id from planned_evidences
		      where experience_id = $1 and (deleted_at is not null or accepted_at is null))
	`, experienceID); err != nil {
		return err
	}

	type planned struct {
		id           uuid.UUID
		name, kind   string
		valueScale   string
		maxScore     *float64
		date         *time.Time
		assessmentID *uuid.UUID
	}
	rows, err := tx.Query(ctx, `
		select pe.id, pe.name, pe.kind, pe.value_scale, pe.max_score, e.class_date, a.id
		  from planned_evidences pe
		  left join session_outline_entries e on e.id = pe.session_entry_id and e.deleted_at is null
		  left join assessments a on a.planned_evidence_id = pe.id and a.deleted_at is null
		 where pe.experience_id = $1 and pe.deleted_at is null and pe.accepted_at is not null
		 order by pe.created_at, pe.id
	`, experienceID)
	if err != nil {
		return err
	}
	var evidences []planned
	for rows.Next() {
		var p planned
		if err := rows.Scan(&p.id, &p.name, &p.kind, &p.valueScale, &p.maxScore, &p.date, &p.assessmentID); err != nil {
			rows.Close()
			return err
		}
		evidences = append(evidences, p)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	if len(evidences) == 0 {
		return nil
	}

	for _, p := range evidences {
		var sessionID *uuid.UUID
		var dueAt *time.Time
		if p.date != nil {
			var sid uuid.UUID
			var end time.Time
			err := tx.QueryRow(ctx, `
				select id, scheduled_end_at from class_sessions
				 where class_id = $1 and session_date = $2 and deleted_at is null and status <> 'cancelled'
				 order by scheduled_start_at limit 1
			`, classID, *p.date).Scan(&sid, &end)
			if err != nil && !errors.Is(err, pgx.ErrNoRows) {
				return err
			}
			if err == nil {
				sessionID, dueAt = &sid, &end
			}
		}
		kind := plannedEvidenceKinds[p.kind]

		assessmentID := uuid.Nil
		if p.assessmentID != nil {
			assessmentID = *p.assessmentID
			if _, err := tx.Exec(ctx, `
				update assessments set title = $2, kind = $3, session_id = $4, due_at = $5
				 where id = $1
				   and (title is distinct from $2 or kind is distinct from $3
				        or session_id is distinct from $4 or due_at is distinct from $5)
			`, assessmentID, p.name, kind, sessionID, dueAt); err != nil {
				return err
			}
			// The scale changes only while nobody has been valued yet: a mark
			// already recorded was written against the old one.
			if _, err := tx.Exec(ctx, `
				update assessments a set value_scale = $2, max_score = $3
				 where a.id = $1
				   and (a.value_scale is distinct from $2 or a.max_score is distinct from $3::numeric)
				   and not exists (select 1 from scores s where s.assessment_id = a.id and s.deleted_at is null)
			`, assessmentID, p.valueScale, p.maxScore); err != nil {
				return err
			}
		} else if err := tx.QueryRow(ctx, `
			insert into assessments (tenant_id, class_id, term_id, session_id,
			                         title, kind, value_scale, max_score, due_at,
			                         status, published_at, planned_evidence_id)
			values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7, $8,
			        'published', now(), $9)
			returning id
		`, classID, termID, sessionID, p.name, kind, p.valueScale, p.maxScore, dueAt, p.id).Scan(&assessmentID); err != nil {
			return err
		}

		// assessment_criteria rows are soft-deleted, so a criterion that
		// returns reuses its old row.
		if _, err := tx.Exec(ctx, `
			update assessment_criteria set deleted_at = now()
			 where assessment_id = $1 and deleted_at is null
			   and criterion_id not in (
			     select criterion_id from planned_evidence_criteria
			      where evidence_id = $2 and deleted_at is null)
		`, assessmentID, p.id); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
			insert into assessment_criteria (tenant_id, assessment_id, criterion_id)
			select app.current_tenant_id(), $1, pc.criterion_id
			  from planned_evidence_criteria pc
			 where pc.evidence_id = $2 and pc.deleted_at is null
			on conflict (tenant_id, assessment_id, criterion_id) do update set deleted_at = null
			 where assessment_criteria.deleted_at is not null
		`, assessmentID, p.id); err != nil {
			return err
		}
	}
	return nil
}

// HealClassPlan is SyncClassPlan for read paths: it runs in a savepoint and
// never fails the read. A class whose sync fails still shows its calendar;
// the evidence simply waits for the next successful sync.
func HealClassPlan(ctx context.Context, tx pgx.Tx, classID uuid.UUID) {
	sp, err := tx.Begin(ctx)
	if err != nil {
		return
	}
	if err := SyncClassPlan(ctx, sp, classID); err != nil {
		slog.WarnContext(ctx, "plan sync skipped", "class_id", classID, "error", err)
		_ = sp.Rollback(ctx)
		return
	}
	_ = sp.Commit(ctx)
}
