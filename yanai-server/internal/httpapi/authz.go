package httpapi

import (
	"context"
	"net/http"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/db"
	"yanai-server/internal/repo"
)

// Per-resource authorization, on top of the per-tenant isolation RLS gives us.
//
// `sessionAuth` establishes that the caller holds a live session and an active
// teacher membership in some school. RLS then scopes every query to that
// school. Neither step says anything about *which classes* the teacher
// teaches — no RLS policy references a teacher, and `WithTenantTx` sets no GUC
// that one could — so without the guards in this file, any teacher in a school
// could read any class's roster and evidence, fetch any voice note's audio,
// discard a colleague's recording, and write official niveles de logro for
// classes they have never taught.
//
// The rule: a teacher reaches a class only while holding a live
// `class_teachers` row for it. Reads and writes alike.
//
// Every handler touching a class-scoped resource calls one of these, inside
// the request's tenant transaction, before doing anything else. They are
// cheap — one indexed `exists` against `class_teachers_teacher_idx` — and the
// cost of forgetting one is another hole of the kind this file exists to
// close, so favour calling them even where it looks redundant.

const (
	codeNotAssignedToClass   = "not_assigned_to_class"
	codeNotAssignedToSubject = "not_assigned_to_subject"
	codeStudentNotInClass    = "student_not_in_class"
)

func forbidden(code, message string) *db.AppError {
	return db.NewAppError(http.StatusForbidden, code, message)
}

// requireClassAccess fails the request unless the acting teacher is assigned
// to the class today.
func (a *API) requireClassAccess(ctx context.Context, tx pgx.Tx, tc db.TenantCtx, classID uuid.UUID) error {
	today, err := repo.TenantToday(ctx, tx, tc.TenantID)
	if err != nil {
		return err
	}
	ok, err := repo.TeacherTeachesClass(ctx, tx, classID, tc.TeacherID, today)
	if err != nil {
		return err
	}
	if !ok {
		return forbidden(codeNotAssignedToClass, "you are not assigned to this class")
	}
	return nil
}

// requireSubjectAccess is the curriculum-authoring equivalent: criterios and
// capacidades hang off a competencia, which belongs to an área that several
// classes may share.
//
// A transversal competencia has no área (uuid.Nil here) and belongs to the
// whole school by definition, so it is allowed through — that is what
// transversal means, not a gap.
func (a *API) requireSubjectAccess(ctx context.Context, tx pgx.Tx, tc db.TenantCtx, subjectID uuid.UUID) error {
	if subjectID == uuid.Nil {
		return nil
	}
	today, err := repo.TenantToday(ctx, tx, tc.TenantID)
	if err != nil {
		return err
	}
	ok, err := repo.TeacherTeachesSubject(ctx, tx, subjectID, tc.TeacherID, today)
	if err != nil {
		return err
	}
	if !ok {
		return forbidden(codeNotAssignedToSubject, "you do not teach this área")
	}
	return nil
}

// requireStudentOnRoster is the second axis. Being assigned to a class is not
// authorization to read any student id someone cares to put in the URL — only
// the ones actually on that class's roster.
func (a *API) requireStudentOnRoster(ctx context.Context, tx pgx.Tx, tc db.TenantCtx, classID, studentID uuid.UUID) error {
	today, err := repo.TenantToday(ctx, tx, tc.TenantID)
	if err != nil {
		return err
	}
	ok, err := repo.StudentOnClassRoster(ctx, tx, classID, studentID, today)
	if err != nil {
		return err
	}
	if !ok {
		return forbidden(codeStudentNotInClass, "that student is not on this class's roster")
	}
	return nil
}

// The id-only routes name a score, an assessment, a voice note — never the
// class. Each resolver below finds the class, then the guard runs as usual.
//
// A resolver returning pgx.ErrNoRows becomes a 404 through the normal error
// mapping. That is deliberate for a wrong-tenant id: RLS has already hidden
// the row, and answering 403 instead would confirm it exists somewhere.

func (a *API) requireSessionAccess(ctx context.Context, tx pgx.Tx, tc db.TenantCtx, sessionID uuid.UUID) (uuid.UUID, error) {
	classID, err := repo.ClassIDForSession(ctx, tx, sessionID)
	if err != nil {
		return uuid.Nil, err
	}
	return classID, a.requireClassAccess(ctx, tx, tc, classID)
}

func (a *API) requireVoiceNoteAccess(ctx context.Context, tx pgx.Tx, tc db.TenantCtx, voiceNoteID uuid.UUID) error {
	classID, err := repo.ClassIDForVoiceNote(ctx, tx, voiceNoteID)
	if err != nil {
		return err
	}
	return a.requireClassAccess(ctx, tx, tc, classID)
}

func (a *API) requireAssessmentAccess(ctx context.Context, tx pgx.Tx, tc db.TenantCtx, assessmentID uuid.UUID) error {
	classID, err := repo.ClassIDForAssessment(ctx, tx, assessmentID)
	if err != nil {
		return err
	}
	return a.requireClassAccess(ctx, tx, tc, classID)
}

func (a *API) requireScoreAccess(ctx context.Context, tx pgx.Tx, tc db.TenantCtx, scoreID uuid.UUID) error {
	classID, err := repo.ClassIDForScore(ctx, tx, scoreID)
	if err != nil {
		return err
	}
	return a.requireClassAccess(ctx, tx, tc, classID)
}

func (a *API) requireCriterionScoreAccess(ctx context.Context, tx pgx.Tx, tc db.TenantCtx, criterionScoreID uuid.UUID) error {
	classID, err := repo.ClassIDForCriterionScore(ctx, tx, criterionScoreID)
	if err != nil {
		return err
	}
	return a.requireClassAccess(ctx, tx, tc, classID)
}

func (a *API) requirePracticeScoreAccess(ctx context.Context, tx pgx.Tx, tc db.TenantCtx, practiceScoreID uuid.UUID) error {
	classID, err := repo.ClassIDForPracticeScore(ctx, tx, practiceScoreID)
	if err != nil {
		return err
	}
	return a.requireClassAccess(ctx, tx, tc, classID)
}

func (a *API) requireCompetencyAccess(ctx context.Context, tx pgx.Tx, tc db.TenantCtx, competencyID uuid.UUID) error {
	subjectID, err := repo.SubjectIDForCompetency(ctx, tx, competencyID)
	if err != nil {
		return err
	}
	return a.requireSubjectAccess(ctx, tx, tc, subjectID)
}

func (a *API) requireCriterionAccess(ctx context.Context, tx pgx.Tx, tc db.TenantCtx, criterionID uuid.UUID) error {
	subjectID, err := repo.SubjectIDForCriterion(ctx, tx, criterionID)
	if err != nil {
		return err
	}
	return a.requireSubjectAccess(ctx, tx, tc, subjectID)
}
