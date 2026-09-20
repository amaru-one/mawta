package repo

import (
	"context"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// Authorization lookups: which class a resource belongs to, and whether a
// teacher is assigned to it.
//
// RLS scopes every query here to one school. It does not scope to one teacher
// — no policy anywhere references a teacher, and there is no GUC carrying one
// — so "same school" was, until this file existed, the only check standing
// between a teacher and every other teacher's classes. These functions are
// what `internal/httpapi` uses to close that gap; see its `authz.go`.
//
// Each resolver returns pgx.ErrNoRows for an id that does not exist *in this
// tenant*, which the caller maps to 404. A wrong-tenant id is therefore
// indistinguishable from a made-up one, which is the correct answer: whether a
// row exists in another school is not something this school gets to learn.

// TeacherTeachesClass reports whether the teacher holds a live assignment to
// the class today.
//
// Any class_teachers role counts — titular, auxiliar, practicante and
// reemplazo are all people who legitimately teach the class. What matters is
// that the assignment exists and covers today: a teacher who covered a class
// last term should not still reach this term's students.
//
// `today` comes from the tenant's own timezone (see TenantToday), not the
// server's clock, so an assignment starting "today" begins when the school
// says it does.
func TeacherTeachesClass(ctx context.Context, tx pgx.Tx, classID, teacherID uuid.UUID, today any) (bool, error) {
	var ok bool
	err := tx.QueryRow(ctx, `
		select exists (
		  select 1 from class_teachers ct
		   where ct.class_id = $1
		     and ct.teacher_id = $2
		     and ct.deleted_at is null
		     and ct.starts_on <= $3
		     and (ct.ends_on is null or ct.ends_on >= $3)
		)`, classID, teacherID, today).Scan(&ok)
	return ok, err
}

// TeacherTeachesSubject reports whether the teacher holds a live assignment to
// any class of the given subject.
//
// This is the authorization unit for the curriculum-authoring routes, which
// name a competencia rather than a class: criterios and capacidades belong to
// a competencia, which belongs to an área, and several classes of that área
// may share them. Scoping those to one class would be wrong — the rows really
// are shared — but leaving them open to the whole school would let a teacher
// rewrite the criterios of an área they do not teach.
func TeacherTeachesSubject(ctx context.Context, tx pgx.Tx, subjectID, teacherID uuid.UUID, today any) (bool, error) {
	var ok bool
	err := tx.QueryRow(ctx, `
		select exists (
		  select 1
		    from class_teachers ct
		    join classes c on c.id = ct.class_id and c.deleted_at is null
		    join courses co on co.id = c.course_id and co.deleted_at is null
		   where ct.teacher_id = $1
		     and co.subject_id = $2
		     and ct.deleted_at is null
		     and ct.starts_on <= $3
		     and (ct.ends_on is null or ct.ends_on >= $3)
		)`, teacherID, subjectID, today).Scan(&ok)
	return ok, err
}

// ClassIDForSession resolves a session to its class.
func ClassIDForSession(ctx context.Context, tx pgx.Tx, sessionID uuid.UUID) (uuid.UUID, error) {
	var classID uuid.UUID
	err := tx.QueryRow(ctx,
		`select class_id from class_sessions where id = $1 and deleted_at is null`, sessionID).Scan(&classID)
	return classID, err
}

// ClassIDForVoiceNote resolves a voice note to its class. voice_notes carries
// class_id directly, denormalised at insert.
func ClassIDForVoiceNote(ctx context.Context, tx pgx.Tx, voiceNoteID uuid.UUID) (uuid.UUID, error) {
	var classID uuid.UUID
	err := tx.QueryRow(ctx,
		`select class_id from voice_notes where id = $1 and deleted_at is null`, voiceNoteID).Scan(&classID)
	return classID, err
}

// ClassIDForAssessment resolves an assessment to its class.
func ClassIDForAssessment(ctx context.Context, tx pgx.Tx, assessmentID uuid.UUID) (uuid.UUID, error) {
	var classID uuid.UUID
	err := tx.QueryRow(ctx,
		`select class_id from assessments where id = $1 and deleted_at is null`, assessmentID).Scan(&classID)
	return classID, err
}

// ClassIDForScore resolves a score to its class. scores carries class_id,
// filled by a trigger from the assessment, so this needs no join.
//
// A superseded score still resolves: correcting one is exactly the operation
// being authorized, and refusing to resolve it would turn a 403 into a
// confusing 404.
func ClassIDForScore(ctx context.Context, tx pgx.Tx, scoreID uuid.UUID) (uuid.UUID, error) {
	var classID uuid.UUID
	err := tx.QueryRow(ctx,
		`select class_id from scores where id = $1 and deleted_at is null`, scoreID).Scan(&classID)
	return classID, err
}

// ClassIDForCriterionScore resolves a criterion score to its class through the
// assessment it was recorded against. criterion_scores carries no class_id of
// its own.
func ClassIDForCriterionScore(ctx context.Context, tx pgx.Tx, criterionScoreID uuid.UUID) (uuid.UUID, error) {
	var classID uuid.UUID
	err := tx.QueryRow(ctx, `
		select a.class_id
		  from criterion_scores cs
		  join assessments a on a.id = cs.assessment_id and a.deleted_at is null
		 where cs.id = $1 and cs.deleted_at is null`, criterionScoreID).Scan(&classID)
	return classID, err
}

// ClassIDForPracticeScore resolves a practice score to its class.
func ClassIDForPracticeScore(ctx context.Context, tx pgx.Tx, practiceScoreID uuid.UUID) (uuid.UUID, error) {
	var classID uuid.UUID
	err := tx.QueryRow(ctx,
		`select class_id from practice_scores where id = $1 and deleted_at is null`, practiceScoreID).Scan(&classID)
	return classID, err
}

// SubjectIDForCompetency resolves a competencia to its área.
//
// A transversal competencia has no subject (competencies_transversal_has_no_subject
// enforces it), so this returns uuid.Nil and no error for one. Callers treat
// that as "shared across the school": a transversal competencia belongs to
// every teacher, which is what transversal means.
func SubjectIDForCompetency(ctx context.Context, tx pgx.Tx, competencyID uuid.UUID) (uuid.UUID, error) {
	var subjectID *uuid.UUID
	if err := tx.QueryRow(ctx,
		`select subject_id from competencies where id = $1 and deleted_at is null`, competencyID).Scan(&subjectID); err != nil {
		return uuid.Nil, err
	}
	if subjectID == nil {
		return uuid.Nil, nil
	}
	return *subjectID, nil
}

// SubjectIDForCriterion resolves a criterio to the área of its competencia.
func SubjectIDForCriterion(ctx context.Context, tx pgx.Tx, criterionID uuid.UUID) (uuid.UUID, error) {
	var subjectID *uuid.UUID
	if err := tx.QueryRow(ctx, `
		select c.subject_id
		  from evaluation_criteria ec
		  join competencies c on c.id = ec.competency_id and c.deleted_at is null
		 where ec.id = $1 and ec.deleted_at is null`, criterionID).Scan(&subjectID); err != nil {
		return uuid.Nil, err
	}
	if subjectID == nil {
		return uuid.Nil, nil
	}
	return *subjectID, nil
}

// StudentOnClassRoster reports whether the student is on the class's roster as
// of the given date. Used to stop a teacher reaching a student who is not
// theirs through a class that is.
func StudentOnClassRoster(ctx context.Context, tx pgx.Tx, classID, studentID uuid.UUID, asOf any) (bool, error) {
	var ok bool
	err := tx.QueryRow(ctx, `
		select exists (
		  select 1
		    from section_memberships sm
		    join classes c on c.section_id = sm.section_id and c.id = $1 and c.deleted_at is null
		   where sm.student_id = $2
		     and sm.deleted_at is null
		     and sm.joined_on <= $3
		     and (sm.left_on is null or sm.left_on > $3)
		)`, classID, studentID, asOf).Scan(&ok)
	return ok, err
}
