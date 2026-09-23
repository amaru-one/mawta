package repo

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// ClassStudent is one row of the class list: who they are, where they stand in
// the competencia being looked at, and how much evidence there is behind that.
//
// Level is nil when the teacher has not asserted one this period. That is a
// real state under RVM 048-2024 5.1.2.2 — "not developed and evaluated this
// period" — and it must never be rendered as C or as a zero.
type ClassStudent struct {
	StudentID uuid.UUID `json:"student_id"`
	FullName  string    `json:"full_name"`
	Level     *string   `json:"level"`
	// EvidenceCount is how many pieces of evidencia this student has in the
	// competencia this period. It is context for the judgement, never an input
	// to it: nothing is computed from the count.
	EvidenceCount int `json:"evidence_count"`
}

// ListClassStudents returns the class roster as of today with each student's
// level in one competencia.
//
// competencyID is optional. Without it the list is just the roster: no level,
// and the evidence count covers the whole área. That is the honest answer when
// a class has no competencias configured yet, rather than an empty screen.
func ListClassStudents(ctx context.Context, tx pgx.Tx, classID uuid.UUID, competencyID *uuid.UUID, termID uuid.UUID, asOf time.Time) ([]ClassStudent, error) {
	rows, err := tx.Query(ctx, `
		select st.id,
		       st.paternal_surname
		         || coalesce(' ' || st.maternal_surname, '')
		         || ', ' || coalesce(st.preferred_name, st.given_name) as full_name,
		       l.code,
		       (select count(*)
		          from assessments a
		         where a.class_id = $1 and a.term_id = $3
		           and a.status = 'published' and a.deleted_at is null
		           and (a.student_id is null or a.student_id = st.id)
		           and ($2::uuid is null or exists (
		                 select 1
		                   from assessment_criteria ac
		                   join evaluation_criteria ec on ec.id = ac.criterion_id
		                  where ac.assessment_id = a.id and ac.deleted_at is null
		                    and ec.competency_id = $2::uuid))
		       ) as evidence_count
		  from section_memberships sm
		  join classes c on c.section_id = sm.section_id and c.id = $1
		  join students st on st.id = sm.student_id and st.deleted_at is null
		  left join competency_term_levels ctl
		         on ctl.student_id = st.id
		        and ctl.competency_id = $2::uuid
		        and ctl.term_id = $3
		        and ctl.superseded_at is null and ctl.deleted_at is null
		  left join grade_scale_levels l on l.id = ctl.scale_level_id
		 where sm.joined_on <= $4 and (sm.left_on is null or sm.left_on > $4)
		   and sm.deleted_at is null and c.deleted_at is null
		 order by st.paternal_surname, st.maternal_surname nulls first, st.given_name
	`, classID, competencyID, termID, asOf)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := []ClassStudent{}
	for rows.Next() {
		var s ClassStudent
		if err := rows.Scan(&s.StudentID, &s.FullName, &s.Level, &s.EvidenceCount); err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

// ListStudentEvidence returns the period's evidencia for one student, narrowed
// to the competencia being judged, each piece carrying its value.
//
// The narrowing goes through assessment_criteria: a piece of evidence belongs
// to a competencia when it is tagged with at least one of that competencia's
// criterios. That is the whole job the criterio tag does — it is how the
// teacher's note of "what to look at" ends up grouping the evidence under the
// thing it informs. Evidence tagged with nothing belongs to no competencia and
// appears only on the student's full grades screen.
//
// Nothing here is aggregated. The list is material for a judgement the teacher
// makes; the level itself is written by AssertCompetencyLevel.
func ListStudentEvidence(ctx context.Context, tx pgx.Tx, classID, studentID uuid.UUID, competencyID *uuid.UUID, termID uuid.UUID) ([]EvaluationEntry, error) {
	rows, err := tx.Query(ctx, `
		select a.id, a.title, a.kind, a.value_scale, a.max_score, a.due_at, gc.code, gc.name,
		       a.student_id is not null as is_personal, a.counts_toward_internal,
		       s.id, s.attempt_number, s.attempt_kind, s.status, s.raw_value
		  from assessments a
		  join grading_components gc on gc.id = a.component_id
		  left join scores s on s.assessment_id = a.id and s.student_id = $2
		                     and s.superseded_at is null and s.deleted_at is null
		 where a.class_id = $1 and a.term_id = $3
		   and a.status = 'published' and a.deleted_at is null
		   and (a.student_id is null or a.student_id = $2)
		   and ($4::uuid is null or exists (
		         select 1
		           from assessment_criteria ac
		           join evaluation_criteria ec on ec.id = ac.criterion_id
		          where ac.assessment_id = a.id and ac.deleted_at is null
		            and ec.competency_id = $4::uuid))
		 order by a.due_at nulls last, a.title, s.attempt_number
	`, classID, studentID, termID, competencyID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	byAssessment := make(map[uuid.UUID]*EvaluationEntry)
	var order []uuid.UUID
	for rows.Next() {
		var e EvaluationEntry
		var scoreID *uuid.UUID
		var attemptNumber *int16
		var attemptKind, status *string
		var rawValue *float64
		if err := rows.Scan(&e.AssessmentID, &e.Title, &e.Kind, &e.ValueScale, &e.MaxScore, &e.DueAt,
			&e.ComponentCode, &e.ComponentName, &e.IsPersonal, &e.CountsTowardInternal,
			&scoreID, &attemptNumber, &attemptKind, &status, &rawValue); err != nil {
			return nil, err
		}
		entry, ok := byAssessment[e.AssessmentID]
		if !ok {
			entry = &e
			entry.Criteria = []CriterionRef{}
			entry.Attempts = []ScoreAttempt{}
			entry.CriterionScores = []CriterionScoreEntry{}
			byAssessment[e.AssessmentID] = entry
			order = append(order, e.AssessmentID)
		}
		if scoreID != nil {
			entry.Attempts = append(entry.Attempts, ScoreAttempt{
				ScoreID: *scoreID, AttemptNumber: *attemptNumber, AttemptKind: *attemptKind,
				Status: *status, RawValue: rawValue,
			})
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	// The criterio tags, read separately: one assessment carries several, and
	// joining them above would multiply the attempt rows.
	critRows, err := tx.Query(ctx, `
		select ac.assessment_id, ec.id, ec.code, ec.description
		  from assessment_criteria ac
		  join assessments a on a.id = ac.assessment_id
		  join evaluation_criteria ec on ec.id = ac.criterion_id
		 where a.class_id = $1 and a.term_id = $2
		   and a.status = 'published' and a.deleted_at is null
		   and (a.student_id is null or a.student_id = $3)
		   and ac.deleted_at is null and ec.deleted_at is null
		 order by ec.sort_order, ec.code
	`, classID, termID, studentID)
	if err != nil {
		return nil, err
	}
	defer critRows.Close()
	for critRows.Next() {
		var assessmentID uuid.UUID
		var ref CriterionRef
		if err := critRows.Scan(&assessmentID, &ref.CriterionID, &ref.Code, &ref.Description); err != nil {
			return nil, err
		}
		if entry, ok := byAssessment[assessmentID]; ok {
			entry.Criteria = append(entry.Criteria, ref)
		}
	}
	if err := critRows.Err(); err != nil {
		return nil, err
	}

	// The independent per-criterio marks, read separately for the same reason
	// GetStudentGrades does: a rubric assessment carries no scores row at all,
	// so its marks would otherwise be invisible here.
	csRows, err := tx.Query(ctx, `
		select cs.assessment_id, cs.id, cs.criterion_id, cs.student_id, cs.value_scale,
		       cs.raw_value, cs.max_value, l.code, cs.recorded_at
		  from criterion_scores cs
		  join assessments a on a.id = cs.assessment_id
		  left join grade_scale_levels l on l.id = cs.scale_level_id
		 where a.class_id = $1 and a.term_id = $2 and cs.student_id = $3
		   and a.status = 'published' and a.deleted_at is null
		   and cs.superseded_at is null and cs.deleted_at is null
		 order by cs.recorded_at
	`, classID, termID, studentID)
	if err != nil {
		return nil, err
	}
	defer csRows.Close()
	for csRows.Next() {
		var assessmentID uuid.UUID
		var entry CriterionScoreEntry
		if err := csRows.Scan(&assessmentID, &entry.ID, &entry.CriterionID, &entry.StudentID, &entry.ValueScale,
			&entry.RawValue, &entry.MaxValue, &entry.Level, &entry.RecordedAt); err != nil {
			return nil, err
		}
		if e, ok := byAssessment[assessmentID]; ok {
			e.CriterionScores = append(e.CriterionScores, entry)
		}
	}
	if err := csRows.Err(); err != nil {
		return nil, err
	}

	out := make([]EvaluationEntry, 0, len(order))
	for _, id := range order {
		out = append(out, *byAssessment[id])
	}
	return out, nil
}
