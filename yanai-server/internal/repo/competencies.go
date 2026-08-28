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

// ListClassCompetencyLevels returns every competency of the class's subject
// with this student's asserted level and conclusion for the term.
//
// The mandatory-conclusion rules for Secundaria EBR (RVM 048-2024):
//   - level C                      → mandatory (5.1.1.3 p.7.d)
//   - C in two or more consecutive
//     periods                      → mandatory, and must justify the lack of
//     progress (5.1.1.3 p.3)
//   - student facing educational
//     barriers                     → mandatory every period, stating supports
//     (5.1.1.3 p.7)
//   - anything else                → optional
func ListClassCompetencyLevels(ctx context.Context, tx pgx.Tx, classID, studentID, termID uuid.UUID) ([]CompetencyLevelRow, error) {
	rows, err := tx.Query(ctx, `
		with cls as (
		  select co.subject_id, t.academic_year_id, t.sequence
		    from classes cl
		    join courses co on co.id = cl.course_id
		    join terms t on t.id = $3
		   where cl.id = $1
		),
		lvl as (
		  select ctl.competency_id, ctl.scale_level_id, ctl.asserted_at,
		         l.code as level_code
		    from competency_term_levels ctl
		    join grade_scale_levels l on l.id = ctl.scale_level_id
		   where ctl.student_id = $2 and ctl.term_id = $3
		     and ctl.superseded_at is null and ctl.deleted_at is null
		),
		-- Was this competency at C in the immediately preceding period?
		prev_c as (
		  select ctl.competency_id
		    from competency_term_levels ctl
		    join terms pt on pt.id = ctl.term_id
		    join grade_scale_levels l on l.id = ctl.scale_level_id
		   where ctl.student_id = $2
		     and pt.academic_year_id = (select academic_year_id from cls)
		     and pt.sequence = (select sequence from cls) - 1
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
		       case
		         when s.inclusion_support then $5
		         when lvl.level_code = $4 and prev_c.competency_id is not null then $6
		         when lvl.level_code = $4 then $7
		         else $8
		       end,
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
	`, classID, studentID, termID,
		domain.LevelC,
		domain.ConclusionInclusionSupport,
		domain.ConclusionConsecutiveC,
		domain.ConclusionLevelC,
		domain.ConclusionOptional)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []CompetencyLevelRow
	for rows.Next() {
		var r CompetencyLevelRow
		if err := rows.Scan(&r.CompetencyID, &r.Code, &r.Name, &r.Kind, &r.SubjectID,
			&r.Level, &r.LevelID, &r.AssertedAt,
			&r.ConclusionRequirement, &r.ConclusionBody, &r.ConclusionStatus); err != nil {
			return nil, err
		}
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
		  (tenant_id, student_id, competency_id, term_id, class_id, scale_level_id,
		   asserted_by_id, note, supersedes_id)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7, $8)
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
// client gets to make.
func UpsertConclusion(ctx context.Context, tx pgx.Tx, classID, studentID, competencyID, termID, teacherID uuid.UUID, body string, includesRecommendations bool, status string) (uuid.UUID, error) {
	if status == domain.ConclusionFinal && !includesRecommendations {
		return uuid.Nil, db.NewAppError(http.StatusUnprocessableEntity, "missing_recommendations",
			"a final conclusión descriptiva must include personalised recommendations (RVM 094-2020, 5.1.1.3 p.7)")
	}

	requirement, err := conclusionRequirement(ctx, tx, studentID, competencyID, termID)
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
		  (tenant_id, student_id, competency_id, term_id, class_id, body,
		   requirement, includes_recommendations, status, authored_by_id, supersedes_id)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
		returning id
	`, studentID, competencyID, termID, classID, body,
		requirement, includesRecommendations, status, teacherID, supersedesID).Scan(&newID)
	return newID, err
}

// conclusionRequirement classifies why a conclusion is (or is not) mandatory
// for this competency, student and period.
func conclusionRequirement(ctx context.Context, tx pgx.Tx, studentID, competencyID, termID uuid.UUID) (string, error) {
	var inclusion bool
	if err := tx.QueryRow(ctx,
		`select inclusion_support from students where id = $1`, studentID).Scan(&inclusion); err != nil {
		return "", err
	}
	if inclusion {
		return domain.ConclusionInclusionSupport, nil
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
	if levelCode == nil || *levelCode != domain.LevelC {
		return domain.ConclusionOptional, nil
	}

	var prevC bool
	if err := tx.QueryRow(ctx, `
		select exists (
		  select 1 from competency_term_levels ctl
		    join terms pt on pt.id = ctl.term_id
		    join grade_scale_levels l on l.id = ctl.scale_level_id
		   where ctl.student_id = $1 and ctl.competency_id = $2
		     and l.code = $3
		     and pt.sequence = (select sequence - 1 from terms where id = $4)
		     and pt.academic_year_id = (select academic_year_id from terms where id = $4)
		     and ctl.superseded_at is null and ctl.deleted_at is null
		)
	`, studentID, competencyID, domain.LevelC, termID).Scan(&prevC); err != nil {
		return "", err
	}
	if prevC {
		return domain.ConclusionConsecutiveC, nil
	}
	return domain.ConclusionLevelC, nil
}

// MissingMandatoryConclusions lists the (student, competency) pairs in a class
// and period that carry a level requiring a conclusión descriptiva but have no
// final one. Closing the period or exporting to SIAGIE must be blocked while
// this is non-empty.
//
// Scoped by the class's *área* and roster rather than by
// competency_term_levels.class_id: that column is provenance only (the norm
// knows competencias and periodos, not classes), so a level asserted from a
// different class must still block its own área and must not block someone
// else's.
type MissingConclusion struct {
	StudentID    uuid.UUID `json:"student_id"`
	StudentName  string    `json:"student_name"`
	CompetencyID uuid.UUID `json:"competency_id"`
	Competency   string    `json:"competency"`
	Requirement  string    `json:"requirement"`
}

func MissingMandatoryConclusions(ctx context.Context, tx pgx.Tx, classID, termID uuid.UUID) ([]MissingConclusion, error) {
	rows, err := tx.Query(ctx, `
		select ctl.student_id,
		       trim(s.given_name || ' ' || s.paternal_surname),
		       c.id, c.name,
		       case when s.inclusion_support then $3 else $4 end
		  from competency_term_levels ctl
		  join students s on s.id = ctl.student_id
		  join competencies c on c.id = ctl.competency_id
		  join grade_scale_levels l on l.id = ctl.scale_level_id
		  left join descriptive_conclusions dc
		         on dc.student_id = ctl.student_id
		        and dc.competency_id = ctl.competency_id
		        and dc.term_id = ctl.term_id
		        and dc.status = 'final'
		        and dc.superseded_at is null and dc.deleted_at is null
		 where ctl.term_id = $2
		   and c.subject_id = (select co.subject_id
		                         from classes cl join courses co on co.id = cl.course_id
		                        where cl.id = $1)
		   and exists (select 1
		                 from section_memberships sm
		                 join classes cl on cl.section_id = sm.section_id
		                                and cl.academic_year_id = sm.academic_year_id
		                where cl.id = $1 and sm.student_id = ctl.student_id
		                  and sm.deleted_at is null)
		   and ctl.superseded_at is null and ctl.deleted_at is null
		   and (l.code = $5 or s.inclusion_support)
		   and dc.id is null
		 order by 2, c.sort_order
	`, classID, termID,
		domain.ConclusionInclusionSupport, domain.ConclusionLevelC, domain.LevelC)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []MissingConclusion
	for rows.Next() {
		var m MissingConclusion
		if err := rows.Scan(&m.StudentID, &m.StudentName, &m.CompetencyID, &m.Competency, &m.Requirement); err != nil {
			return nil, err
		}
		out = append(out, m)
	}
	return out, rows.Err()
}
