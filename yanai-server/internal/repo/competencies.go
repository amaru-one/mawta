package repo

import (
	"context"
	"net/http"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/db"
	"yanai-server/internal/domain"
)

// CompetencyLevelRow is one competency of one class, with the level asserted
// for a student this period. There is deliberately no suggested level.
type CompetencyLevelRow struct {
	CompetencyID uuid.UUID  `json:"competency_id"`
	Code         string     `json:"code"`
	Name         string     `json:"name"`
	Kind         string     `json:"kind"`
	SubjectID    *uuid.UUID `json:"subject_id"`
	// Level is the asserted nivel de logro — the official record. Null means
	// the competency has not been assessed this period, which is a valid state
	// (5.1.2.2 p.1) and must not be rendered as C.
	Level      *string    `json:"level"`
	LevelID    *uuid.UUID `json:"level_id"`
	AssertedAt *string    `json:"asserted_at"`
	// ConclusionRequired says whether a conclusión descriptiva is mandatory,
	// and ConclusionRequirement why. Computed server-side from the live level
	// and the student, never trusted from the client.
	ConclusionRequired    bool    `json:"conclusion_required"`
	ConclusionRequirement string  `json:"conclusion_requirement"`
	ConclusionBody        *string `json:"conclusion_body"`
	ConclusionStatus      *string `json:"conclusion_status"`
}

// classifyConclusionRequirement decides why a conclusión descriptiva is (or
// isn't) mandatory, per the grade-level-dependent obligatoriedad: inclusion
// support is mandatory every period regardless of level or grade;
// Inicial Ciclo I requires one for every competencia regardless of level;
// otherwise the level itself is mandatory or not depending on the student's
// nivel educativo (level C in Secundaria/Primaria/Inicial Ciclo II, level B
// in Primaria/Inicial Ciclo II, level A only in Inicial Ciclo II). C also
// carries the stronger consecutive_c classification when the competency was
// C in the immediately preceding period too (RVM 048-2024, 5.1.1.3 p.3).
func classifyConclusionRequirement(inclusionSupport bool, stage, cycle string, levelCode *string, consecutiveC bool) string {
	if inclusionSupport {
		return domain.ConclusionInclusionSupport
	}
	if stage == domain.StageInicial && cycle == domain.CycleI {
		return domain.ConclusionCycleIMandatory
	}
	if levelCode == nil {
		return domain.ConclusionOptional
	}
	inicialCycleII := stage == domain.StageInicial && cycle == domain.CycleII
	switch *levelCode {
	case domain.LevelC:
		if consecutiveC {
			return domain.ConclusionConsecutiveC
		}
		return domain.ConclusionLevelC
	case domain.LevelB:
		if stage == domain.StagePrimaria || inicialCycleII {
			return domain.ConclusionLevelB
		}
	case domain.LevelA:
		if inicialCycleII {
			return domain.ConclusionLevelA
		}
	}
	return domain.ConclusionOptional
}

// ListClassCompetencyLevels returns every competency of the class's subject
// with this student's asserted level and conclusion for the term.
func ListClassCompetencyLevels(ctx context.Context, tx pgx.Tx, classID, studentID, termID uuid.UUID) ([]CompetencyLevelRow, error) {
	var stage, cycle string
	if err := tx.QueryRow(ctx, `
		select gl.stage, coalesce(gl.cycle, '')
		  from classes cl
		  join courses co on co.id = cl.course_id
		  join grade_levels gl on gl.id = co.grade_level_id
		 where cl.id = $1
	`, classID).Scan(&stage, &cycle); err != nil {
		return nil, err
	}

	rows, err := tx.Query(ctx, `
		with cls as (
		  select co.subject_id
		    from classes cl
		    join courses co on co.id = cl.course_id
		   where cl.id = $1
		),
		lvl as (
		  select ctl.competency_id, ctl.scale_level_id, ctl.asserted_at,
		         ctl.term_id, l.code as level_code
		    from competency_term_levels ctl
		    join grade_scale_levels l on l.id = ctl.scale_level_id
		   where ctl.student_id = $2 and ctl.term_id = $3
		     and ctl.superseded_at is null and ctl.deleted_at is null
		),
		-- Was this competency at C in the immediately preceding period (same
		-- academic year, sequence - 1)?
		prev_c as (
		  select ctl.competency_id
		    from competency_term_levels ctl
		    join terms pt on pt.id = ctl.term_id
		    join terms t on t.id = $3
		    join grade_scale_levels l on l.id = ctl.scale_level_id
		   where ctl.student_id = $2
		     and pt.academic_year_id = t.academic_year_id
		     and pt.sequence = t.sequence - 1
		     and l.code = $4
		     and ctl.superseded_at is null and ctl.deleted_at is null
		),
		concl as (
		  select competency_id, body, status
		    from descriptive_conclusions
		   where student_id = $2 and term_id = $3
		     and superseded_at is null and deleted_at is null
		)
		select c.id, c.code, c.name, c.kind, c.subject_id,
		       lvl.level_code, lvl.scale_level_id,
		       to_char(lvl.asserted_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
		       s.inclusion_support, prev_c.competency_id is not null,
		       concl.body, concl.status
		  from competencies c
		  cross join students s
		  left join lvl on lvl.competency_id = c.id
		  left join prev_c on prev_c.competency_id = c.id
		  left join concl on concl.competency_id = c.id
		 where s.id = $2
		   and c.subject_id = (select subject_id from cls)
		   and c.is_active and c.deleted_at is null
		 order by c.sort_order, c.code
	`, classID, studentID, termID, domain.LevelC)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []CompetencyLevelRow
	for rows.Next() {
		var r CompetencyLevelRow
		var inclusionSupport, consecutiveC bool
		if err := rows.Scan(&r.CompetencyID, &r.Code, &r.Name, &r.Kind, &r.SubjectID,
			&r.Level, &r.LevelID, &r.AssertedAt,
			&inclusionSupport, &consecutiveC,
			&r.ConclusionBody, &r.ConclusionStatus); err != nil {
			return nil, err
		}
		r.ConclusionRequirement = classifyConclusionRequirement(inclusionSupport, stage, cycle, r.Level, consecutiveC)
		r.ConclusionRequired = r.ConclusionRequirement != domain.ConclusionOptional
		out = append(out, r)
	}
	return out, rows.Err()
}

// AssertCompetencyLevel records a teacher's nivel de logro for one competency
// in one period, superseding any level already on record.
//
// This is the only way an official level is ever written, and nothing
// whatsoever is derived into it. Under RVM 094-2020 the level is the
// teacher's judgement of the period's evidence against the criterios de
// evaluación (5.1.1.3 p.2-3) — not a number the system computes and offers
// first. suggested_level_id and computed_grade_id are deliberately left null:
// the weighted internal system must not shadow the official record.
func AssertCompetencyLevel(ctx context.Context, tx pgx.Tx, classID, studentID, competencyID, termID, teacherID uuid.UUID, levelCode string, note *string) (uuid.UUID, error) {
	var levelID uuid.UUID
	err := tx.QueryRow(ctx, `
		select l.id
		  from grade_scale_levels l
		  join grade_scales g on g.id = l.scale_id
		 where g.kind = 'ordinal' and l.code = $1
		   and l.deleted_at is null and g.deleted_at is null
		 limit 1
	`, levelCode).Scan(&levelID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return uuid.Nil, db.NewAppError(http.StatusBadRequest, "unknown_level",
				"level must be one of AD, A, B or C")
		}
		return uuid.Nil, err
	}

	var supersedesID *uuid.UUID
	var old uuid.UUID
	err = tx.QueryRow(ctx, `
		update competency_term_levels set superseded_at = now()
		 where student_id = $1 and competency_id = $2 and term_id = $3
		   and superseded_at is null and deleted_at is null
		returning id
	`, studentID, competencyID, termID).Scan(&old)
	switch err {
	case nil:
		supersedesID = &old
	case pgx.ErrNoRows:
		// First assertion for this competency and period.
	default:
		return uuid.Nil, err
	}

	var newID uuid.UUID
	err = tx.QueryRow(ctx, `
		insert into competency_term_levels
		  (tenant_id, student_id, competency_id, academic_year_id, term_id, class_id, scale_level_id,
		   asserted_by_id, note, supersedes_id)
		select app.current_tenant_id(), $1, $2, c.academic_year_id, $3, $4, $5, $6, $7, $8
		  from classes c where c.id = $4
		returning id
	`, studentID, competencyID, termID, classID, levelID,
		teacherID, note, supersedesID).Scan(&newID)
	return newID, err
}

// UpsertConclusion writes a conclusión descriptiva, superseding any previous
// one for the same competency and period.
//
// requirement is derived here, never taken from the request: whether a
// conclusion is mandatory is a fact about the student's level, not a claim the
// client gets to make. RVM 094-2020 5.1.1.3 p.7 requires every conclusión to
// carry personalised recommendations, but that lives in body's free text —
// there is no separate flag to validate, because nothing can verify text
// actually contains a recommendation.
func UpsertConclusion(ctx context.Context, tx pgx.Tx, classID, studentID, competencyID, termID, teacherID uuid.UUID, body string, status string) (uuid.UUID, error) {
	requirement, err := conclusionRequirement(ctx, tx, classID, studentID, competencyID, termID)
	if err != nil {
		return uuid.Nil, err
	}

	var supersedesID *uuid.UUID
	var old uuid.UUID
	err = tx.QueryRow(ctx, `
		update descriptive_conclusions set superseded_at = now()
		 where student_id = $1 and competency_id = $2 and term_id = $3
		   and superseded_at is null and deleted_at is null
		returning id
	`, studentID, competencyID, termID).Scan(&old)
	switch err {
	case nil:
		supersedesID = &old
	case pgx.ErrNoRows:
	default:
		return uuid.Nil, err
	}

	var newID uuid.UUID
	err = tx.QueryRow(ctx, `
		insert into descriptive_conclusions
		  (tenant_id, student_id, competency_id, academic_year_id, term_id, class_id, body,
		   requirement, status, authored_by_id, supersedes_id)
		select app.current_tenant_id(), $1, $2, c.academic_year_id, $3, $4, $5, $6, $7, $8, $9
		  from classes c where c.id = $4
		returning id
	`, studentID, competencyID, termID, classID, body,
		requirement, status, teacherID, supersedesID).Scan(&newID)
	return newID, err
}

// conclusionRequirement classifies why a conclusion is (or is not) mandatory
// for this competency, student and period.
func conclusionRequirement(ctx context.Context, tx pgx.Tx, classID, studentID, competencyID, termID uuid.UUID) (string, error) {
	var stage, cycle string
	if err := tx.QueryRow(ctx, `
		select gl.stage, coalesce(gl.cycle, '')
		  from classes cl
		  join courses co on co.id = cl.course_id
		  join grade_levels gl on gl.id = co.grade_level_id
		 where cl.id = $1
	`, classID).Scan(&stage, &cycle); err != nil {
		return "", err
	}

	var inclusion bool
	if err := tx.QueryRow(ctx,
		`select inclusion_support from students where id = $1`, studentID).Scan(&inclusion); err != nil {
		return "", err
	}

	var levelCode *string
	if err := tx.QueryRow(ctx, `
		select l.code from competency_term_levels ctl
		  join grade_scale_levels l on l.id = ctl.scale_level_id
		 where ctl.student_id = $1 and ctl.competency_id = $2 and ctl.term_id = $3
		   and ctl.superseded_at is null and ctl.deleted_at is null
	`, studentID, competencyID, termID).Scan(&levelCode); err != nil && err != pgx.ErrNoRows {
		return "", err
	}

	var consecutiveC bool
	if levelCode != nil && *levelCode == domain.LevelC {
		if err := tx.QueryRow(ctx, `
			select exists (
			  select 1 from competency_term_levels ctl
			    join terms pt on pt.id = ctl.term_id
			    join terms t on t.id = $4
			    join grade_scale_levels l on l.id = ctl.scale_level_id
			   where ctl.student_id = $1 and ctl.competency_id = $2
			     and pt.academic_year_id = t.academic_year_id
			     and pt.sequence = t.sequence - 1
			     and l.code = $3
			     and ctl.superseded_at is null and ctl.deleted_at is null
			)
		`, studentID, competencyID, domain.LevelC, termID).Scan(&consecutiveC); err != nil {
			return "", err
		}
	}

	return classifyConclusionRequirement(inclusion, stage, cycle, levelCode, consecutiveC), nil
}
