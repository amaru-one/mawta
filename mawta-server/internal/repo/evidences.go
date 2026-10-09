package repo

import (
	"context"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/db"
	"mawta-server/internal/domain"
)

// ScoreView is the live valuation of one student on one evidence: the single
// row of scores with superseded_at null. Exactly one of RawValue/Level is set
// when the evidence was valued; both are null for a status like
// not_submitted, which carries no value at all.
type ScoreView struct {
	ScoreID uuid.UUID `json:"score_id"`
	Status  string    `json:"status"`
	// RawValue is the mark the teacher wrote, out of the evidence's MaxScore.
	RawValue *float64 `json:"raw_value"`
	// Percentage is RawValue over MaxScore, for display only. It never derives
	// a nivel de logro.
	Percentage *float64 `json:"percentage"`
	// Level is the AD/A/B/C code the teacher gave this piece of work. It is not
	// the nivel de logro of the competencia.
	Level *string `json:"level"`
}

// CriterionRef names one criterio de evaluación a piece of evidencia is tagged
// with: what the teacher set out to look at in this work. It carries no level
// and must not grow one.
type CriterionRef struct {
	CriterionID uuid.UUID `json:"criterion_id"`
	Code        *string   `json:"code"`
	Description string    `json:"description"`
}

// EvaluationEntry is one piece of evidence — a task, an exam — with the
// student's valuation of it. It carries no weight: under RVM 094-2020 a mark
// informs the teacher's judgement of the criterios and never feeds a final
// grade arithmetically.
type EvaluationEntry struct {
	AssessmentID uuid.UUID `json:"assessment_id"`
	Title        string    `json:"title"`
	Kind         string    `json:"kind"`
	// ValueScale is 'numeric' (a mark out of MaxScore) or 'ordinal' (an
	// AD/A/B/C level; MaxScore is null).
	ValueScale string     `json:"value_scale"`
	MaxScore   *float64   `json:"max_score"`
	DueAt      *time.Time `json:"due_at"`
	// IsPersonal is true when the assessment was created for this student
	// alone (assessments.student_id set) rather than for the whole class.
	IsPersonal bool           `json:"is_personal"`
	Criteria   []CriterionRef `json:"criteria"`
	// Score is nil until the teacher values this student's work.
	Score *ScoreView `json:"score"`
}

// NewAssessment is one piece of evidence to file. StudentID nil means the
// whole class — the original and still the common case; set, the assessment
// is evidencia for that student alone (a recovery task, a re-done project).
// CriterionIDs are the criterios de evaluación the evidence speaks to; there
// must be at least one, since that is how the evidence reaches a competencia.
type NewAssessment struct {
	ClassID   uuid.UUID
	TermID    uuid.UUID
	TeacherID uuid.UUID
	StudentID *uuid.UUID
	Title     string
	Kind      string
	// ValueScale is 'numeric' (MaxScore required and positive) or 'ordinal'
	// (MaxScore must be nil).
	ValueScale   string
	MaxScore     *float64
	DueAt        *string
	CriterionIDs []uuid.UUID
}

func CreateAssessment(ctx context.Context, tx pgx.Tx, a NewAssessment) (uuid.UUID, error) {
	if len(a.CriterionIDs) == 0 {
		return uuid.Nil, db.NewAppError(http.StatusBadRequest, "criteria_required",
			"an evidence needs at least one criterio: that is how it reaches a competencia")
	}
	if a.StudentID != nil {
		// The student must actually be on this class's roster. Without this a
		// teacher could file evidence against a student from another section
		// by id, and it would show up on that student's screen.
		var ok bool
		if err := tx.QueryRow(ctx, `
			select exists (
			  select 1 from classes cl
			    join section_memberships sm on sm.section_id = cl.section_id
			   where cl.id = $1 and sm.student_id = $2
			     and sm.joined_on <= current_date
			     and (sm.left_on is null or sm.left_on > current_date)
			     and sm.deleted_at is null and cl.deleted_at is null
			)
		`, a.ClassID, *a.StudentID).Scan(&ok); err != nil {
			return uuid.Nil, err
		}
		if !ok {
			return uuid.Nil, db.NewAppError(http.StatusBadRequest, "student_not_in_class",
				"that student is not on this class's roster")
		}
	}

	var id uuid.UUID
	err := tx.QueryRow(ctx, `
		insert into assessments (tenant_id, class_id, term_id, student_id,
		                          title, kind, value_scale, max_score, due_at,
		                          status, published_at, created_by_id)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7, $8, 'published', now(), $9)
		returning id
	`, a.ClassID, a.TermID, a.StudentID,
		a.Title, a.Kind, a.ValueScale, a.MaxScore, a.DueAt, a.TeacherID).Scan(&id)
	if err != nil {
		return uuid.Nil, err
	}

	if err := linkAssessmentCriteria(ctx, tx, a.ClassID, a.TermID, id, a.CriterionIDs); err != nil {
		return uuid.Nil, err
	}
	return id, nil
}

// linkAssessmentCriteria records which criterios de evaluación an assessment
// evidences. Every criterio must belong to a competencia of the class's área
// — the same guard CreateCriterion applies when the criterio is written. A
// criterio of an experiencia must also be one ListEvidenceCriteria offers:
// accepted, of a planned experiencia of this class and term. Without this a
// teacher could tag evidence with another class's criterio, which shares the
// área, or with a draft the plan never committed to.
func linkAssessmentCriteria(ctx context.Context, tx pgx.Tx, classID, termID, assessmentID uuid.UUID, criterionIDs []uuid.UUID) error {
	var inClass int
	if err := tx.QueryRow(ctx, `
		select count(*)
		  from evaluation_criteria ec
		  join competencies c on c.id = ec.competency_id
		  join courses co on co.subject_id = c.subject_id
		  join classes cl on cl.course_id = co.id
		 where cl.id = $1 and ec.id = any($2::uuid[])
		   and ec.deleted_at is null and c.deleted_at is null and cl.deleted_at is null
		   and (ec.experience_id is null or (
		         ec.accepted_at is not null and exists (
		           select 1 from learning_experiences le
		            where le.id = ec.experience_id and le.class_id = $1 and le.term_id = $3
		              and le.status = 'planificada' and le.deleted_at is null)))
	`, classID, criterionIDs, termID).Scan(&inClass); err != nil {
		return err
	}
	if inClass != len(criterionIDs) {
		return db.NewAppError(http.StatusBadRequest, "criterion_not_in_class",
			"one of those criterios does not belong to this class's área or to a planned experiencia of this class and period")
	}

	_, err := tx.Exec(ctx, `
		insert into assessment_criteria (tenant_id, assessment_id, criterion_id)
		select app.current_tenant_id(), $1, unnest($2::uuid[])
	`, assessmentID, criterionIDs)
	return err
}

// DeleteAssessment soft-deletes a piece of evidence. The scores recorded
// against it are left alone: they stay in the student's history exactly as
// deleted criterios keep the levels recorded against them.
func DeleteAssessment(ctx context.Context, tx pgx.Tx, assessmentID uuid.UUID) (DeletedAssessment, error) {
	var d DeletedAssessment
	err := tx.QueryRow(ctx, `
		update assessments set deleted_at = now()
		 where id = $1 and deleted_at is null
		returning class_id, term_id, student_id
	`, assessmentID).Scan(&d.ClassID, &d.TermID, &d.StudentID)
	if err == pgx.ErrNoRows {
		return d, db.NewAppError(http.StatusNotFound, "assessment_not_found",
			"that evidence no longer exists")
	}
	return d, err
}

// DeletedAssessment is what the caller needs to log a delete: StudentID nil
// means the evidence was class-wide.
type DeletedAssessment struct {
	ClassID   uuid.UUID
	TermID    uuid.UUID
	StudentID *uuid.UUID
}

// scoreValue is what a valuation carries: a mark, or a level, or neither.
type scoreValue struct {
	Status string
	Raw    *float64
	Level  *string
}

// checkValue rejects a value that does not fit the evidence's scale before it
// reaches the database, so the teacher gets a message instead of a constraint
// name. The database enforces the same rules (sync_score_denormalised).
func checkValue(valueScale string, maxScore *float64, v scoreValue) error {
	if v.Status != domain.ScoreGraded {
		if v.Raw != nil || v.Level != nil {
			return db.NewAppError(http.StatusBadRequest, "value_not_allowed",
				"a status other than graded carries no value")
		}
		return nil
	}
	switch valueScale {
	case domain.ValueScaleNumeric:
		if v.Level != nil {
			return db.NewAppError(http.StatusBadRequest, "level_on_numeric",
				"this evidence is valued with a mark, not a level")
		}
		if v.Raw == nil {
			return db.NewAppError(http.StatusBadRequest, "value_required", "a graded score needs a mark")
		}
		if *v.Raw < 0 || (maxScore != nil && *v.Raw > *maxScore) {
			return db.NewAppError(http.StatusBadRequest, "mark_out_of_range",
				"the mark must be between 0 and the maximum of this evidence")
		}
	case domain.ValueScaleOrdinal:
		if v.Raw != nil {
			return db.NewAppError(http.StatusBadRequest, "mark_on_ordinal",
				"this evidence is valued with a level, not a mark")
		}
		if v.Level == nil {
			return db.NewAppError(http.StatusBadRequest, "value_required", "a graded score needs a level")
		}
	}
	return nil
}

// levelID resolves an AD/A/B/C code to the tenant's ordinal scale level.
func levelID(ctx context.Context, tx pgx.Tx, code string) (uuid.UUID, error) {
	var id uuid.UUID
	err := tx.QueryRow(ctx, `
		select l.id
		  from grade_scale_levels l
		  join grade_scales s on s.id = l.scale_id and s.tenant_id = l.tenant_id
		 where s.kind = 'ordinal' and l.code = $1
		   and l.deleted_at is null and s.deleted_at is null
	`, code).Scan(&id)
	if err == pgx.ErrNoRows {
		return uuid.Nil, db.NewAppError(http.StatusBadRequest, "invalid_level",
			"level must be one of AD, A, B, C")
	}
	return id, err
}

// assessmentScale reads what a valuation has to be checked against.
func assessmentScale(ctx context.Context, tx pgx.Tx, assessmentID uuid.UUID) (valueScale string, maxScore *float64, err error) {
	err = tx.QueryRow(ctx, `
		select value_scale, max_score from assessments
		 where id = $1 and deleted_at is null
	`, assessmentID).Scan(&valueScale, &maxScore)
	if err == pgx.ErrNoRows {
		err = db.NewAppError(http.StatusNotFound, "assessment_not_found", "that evidence no longer exists")
	}
	return
}

// CreateScore records the first valuation of a student on an evidence.
func CreateScore(ctx context.Context, tx pgx.Tx, assessmentID, studentID, teacherID uuid.UUID, status string, rawValue *float64, level *string) (id, classID, termID uuid.UUID, err error) {
	valueScale, maxScore, err := assessmentScale(ctx, tx, assessmentID)
	if err != nil {
		return
	}
	if err = checkValue(valueScale, maxScore, scoreValue{Status: status, Raw: rawValue, Level: level}); err != nil {
		return
	}
	var scaleLevel *uuid.UUID
	if level != nil {
		var lid uuid.UUID
		if lid, err = levelID(ctx, tx, *level); err != nil {
			return
		}
		scaleLevel = &lid
	}
	// max_value comes from the assessment, so it's always the denominator the
	// score was recorded out of, even if the assessment's own max changes later.
	err = tx.QueryRow(ctx, `
		insert into scores (tenant_id, assessment_id, student_id, status, raw_value, max_value,
		                     scale_level_id, source, recorded_by_id)
		select app.current_tenant_id(), $1, $2, $3, $4, a.max_score, $5, 'manual', $6
		  from assessments a where a.id = $1
		returning id, class_id, term_id
	`, assessmentID, studentID, status, rawValue, scaleLevel, teacherID).Scan(&id, &classID, &termID)
	return
}

// CorrectScore implements the supersede protocol: it stamps superseded_at on
// the live row first, then inserts the replacement with supersedes_id set —
// in that order, in the same transaction — because scores_live_key is a
// partial unique index and cannot be deferred.
//
// A correction that names nothing inherits the old value, except that a
// status other than graded carries no value at all.
func CorrectScore(ctx context.Context, tx pgx.Tx, scoreID, teacherID uuid.UUID, rawValue *float64, level *string, status *string) (newScoreID, studentID, classID, termID uuid.UUID, err error) {
	var assessmentID uuid.UUID
	var oldStatus string
	var oldRaw *float64
	var oldLevel *string
	err = tx.QueryRow(ctx, `
		select s.assessment_id, s.student_id, s.status, s.raw_value, l.code
		  from scores s
		  left join grade_scale_levels l on l.id = s.scale_level_id
		 where s.id = $1 and s.superseded_at is null and s.deleted_at is null
	`, scoreID).Scan(&assessmentID, &studentID, &oldStatus, &oldRaw, &oldLevel)
	if err != nil {
		if err == pgx.ErrNoRows {
			err = db.NewAppError(http.StatusConflict, "already_superseded", "score already superseded; reload and try again")
		}
		return
	}
	valueScale, maxScore, err := assessmentScale(ctx, tx, assessmentID)
	if err != nil {
		return
	}

	newStatus := oldStatus
	if status != nil {
		newStatus = *status
	}
	newRaw, newLevel := oldRaw, oldLevel
	if rawValue != nil {
		newRaw = rawValue
	}
	if level != nil {
		newLevel = level
	}
	// not_submitted and its siblings carry no value; keeping the old mark
	// would leave a number on a row that says nothing was handed in.
	if newStatus != domain.ScoreGraded {
		newRaw, newLevel = nil, nil
	}
	if err = checkValue(valueScale, maxScore, scoreValue{Status: newStatus, Raw: newRaw, Level: newLevel}); err != nil {
		return
	}
	var scaleLevel *uuid.UUID
	if newLevel != nil {
		var lid uuid.UUID
		if lid, err = levelID(ctx, tx, *newLevel); err != nil {
			return
		}
		scaleLevel = &lid
	}

	if _, err = tx.Exec(ctx, `update scores set superseded_at = now() where id = $1`, scoreID); err != nil {
		return
	}
	err = tx.QueryRow(ctx, `
		insert into scores (tenant_id, assessment_id, student_id, status, raw_value, max_value,
		                     scale_level_id, source, recorded_by_id, supersedes_id)
		select app.current_tenant_id(), $1, $2, $3, $4, a.max_score, $5, 'manual', $6, $7
		  from assessments a where a.id = $1
		returning id, class_id, term_id
	`, assessmentID, studentID, newStatus, newRaw, scaleLevel, teacherID, scoreID,
	).Scan(&newScoreID, &classID, &termID)
	return
}
