package repo

import (
	"context"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/db"
)

// CriterionEvidence is one cell of the evidencia × criterio grid: the level
// this student reached against one criterio, read off one specific piece of
// evidence. This is the grain RVM 094-2020 works in — 5.1.1.3 p.3 values
// *evidence* through the criterio, so a level always names what it was read
// from.
type CriterionEvidence struct {
	AssessmentID uuid.UUID  `json:"assessment_id"`
	Title        string     `json:"title"`
	Kind         string     `json:"kind"`
	DueAt        *time.Time `json:"due_at"`
	IsPersonal   bool       `json:"is_personal"`
	Level        string     `json:"level"`
}

// CriterionRow is one criterio de evaluación: the teacher's own precisado of
// what they will judge a competencia against, optionally anchored to a CNEB
// desempeño (performance_standards).
type CriterionRow struct {
	CriterionID uuid.UUID  `json:"criterion_id"`
	Code        *string    `json:"code"`
	Description string     `json:"description"`
	SortOrder   int16      `json:"sort_order"`
	StandardID  *uuid.UUID `json:"performance_standard_id"`
	// Evidence is this criterio's row across the period's evidence, oldest
	// first, when the listing is scoped to a student. Reading it left to right
	// is the whole point: C → B → A → A is a student who learned to justify,
	// which no single value can express. Empty means nothing has been judged
	// against this criterio yet — a real state, not a C.
	Evidence []CriterionEvidence `json:"evidence"`
	// PeriodLevel is the legacy period-grain judgement, written before
	// 2026-08-28 by a version of this app that let a teacher value a criterio
	// with no evidence in hand. Read-only history; see the comment on
	// ecs_live_term_key in migration 00005.
	PeriodLevel *string `json:"period_level"`
}

// CompetencyCriteriaRow is one competencia with the criterios the teacher has
// written for it. A competencia with no criterios is returned with an empty
// list rather than omitted: "this competencia still needs criterios" is the
// single most useful thing the screen can say.
type CompetencyCriteriaRow struct {
	CompetencyID uuid.UUID      `json:"competency_id"`
	Code         string         `json:"code"`
	Name         string         `json:"name"`
	Kind         string         `json:"kind"`
	Criteria     []CriterionRow `json:"criteria"`
}

// ListClassCriteria returns every competencia of the class's área with its
// criterios. When studentID is non-nil each criterio also carries that
// student's evidencia × criterio row for the term — the grid the teacher reads
// left to right before asserting the competency level.
func ListClassCriteria(ctx context.Context, tx pgx.Tx, classID uuid.UUID, studentID *uuid.UUID, termID uuid.UUID) ([]CompetencyCriteriaRow, error) {
	rows, err := tx.Query(ctx, `
		with cls as (
		  select co.subject_id
		    from classes cl
		    join courses co on co.id = cl.course_id
		   where cl.id = $1 and cl.deleted_at is null
		)
		select c.id, c.code, c.name, c.kind,
		       ec.id, ec.code, ec.description, ec.sort_order, ec.performance_standard_id,
		       l.code
		  from competencies c
		  left join evaluation_criteria ec
		         on ec.competency_id = c.id and ec.is_active and ec.deleted_at is null
		  -- The legacy period-grain judgement only. The evidence-anchored
		  -- levels are a second query: one criterio has many, and joining them
		  -- here would multiply every competencia row.
		  left join evaluation_criterion_scores ecs
		         on ecs.criterion_id = ec.id
		        and ecs.assessment_id is null
		        and ecs.student_id = $2::uuid
		        and ecs.term_id = $3
		        and ecs.superseded_at is null and ecs.deleted_at is null
		  left join grade_scale_levels l on l.id = ecs.scale_level_id
		 where c.subject_id = (select subject_id from cls)
		   and c.is_active and c.deleted_at is null
		 order by c.sort_order, c.code, ec.sort_order nulls last, ec.code nulls last
	`, classID, studentID, termID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []CompetencyCriteriaRow
	byCompetency := make(map[uuid.UUID]int)
	criterionAt := make(map[uuid.UUID][2]int)
	for rows.Next() {
		var comp CompetencyCriteriaRow
		var crit CriterionRow
		// A competencia with no criterios still produces a row (left join), so
		// every criterio column arrives null and has to be scanned as such.
		var critID *uuid.UUID
		var sortOrder *int16
		var description *string
		if err := rows.Scan(&comp.CompetencyID, &comp.Code, &comp.Name, &comp.Kind,
			&critID, &crit.Code, &description, &sortOrder, &crit.StandardID,
			&crit.PeriodLevel); err != nil {
			return nil, err
		}
		idx, ok := byCompetency[comp.CompetencyID]
		if !ok {
			comp.Criteria = []CriterionRow{}
			out = append(out, comp)
			idx = len(out) - 1
			byCompetency[comp.CompetencyID] = idx
		}
		if critID != nil {
			crit.CriterionID = *critID
			if description != nil {
				crit.Description = *description
			}
			if sortOrder != nil {
				crit.SortOrder = *sortOrder
			}
			crit.Evidence = []CriterionEvidence{}
			out[idx].Criteria = append(out[idx].Criteria, crit)
			criterionAt[*critID] = [2]int{idx, len(out[idx].Criteria) - 1}
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if studentID == nil {
		return out, nil
	}

	// The grid itself: every level this student has against any of those
	// criterios, oldest evidence first. Ordered by due date rather than by
	// when it was marked, because the row is read as a trajectory and what
	// orders a trajectory is when the work happened.
	cells, err := tx.Query(ctx, `
		select ecs.criterion_id, a.id, a.title, a.kind, a.due_at,
		       a.student_id is not null, l.code
		  from evaluation_criterion_scores ecs
		  join assessments a on a.id = ecs.assessment_id and a.deleted_at is null
		  join grade_scale_levels l on l.id = ecs.scale_level_id
		 where ecs.student_id = $1 and ecs.class_id = $2 and ecs.term_id = $3
		   and ecs.assessment_id is not null
		   and ecs.superseded_at is null and ecs.deleted_at is null
		 order by a.due_at nulls last, a.created_at
	`, *studentID, classID, termID)
	if err != nil {
		return nil, err
	}
	defer cells.Close()

	for cells.Next() {
		var criterionID uuid.UUID
		var cell CriterionEvidence
		if err := cells.Scan(&criterionID, &cell.AssessmentID, &cell.Title, &cell.Kind,
			&cell.DueAt, &cell.IsPersonal, &cell.Level); err != nil {
			return nil, err
		}
		// A level against a criterio the class no longer lists (soft-deleted,
		// or belonging to another competencia) has nowhere to go on this
		// screen. It stays in the student's history; it is just not drawn here.
		if at, ok := criterionAt[criterionID]; ok {
			out[at[0]].Criteria[at[1]].Evidence = append(out[at[0]].Criteria[at[1]].Evidence, cell)
		}
	}
	return out, cells.Err()
}

// CreateCriterion records a criterio the teacher wrote for one competencia.
//
// The description is the whole point — it is the sentence the teacher will
// judge evidence against — so a blank one is rejected here rather than
// stored and rendered as an empty row.
func CreateCriterion(ctx context.Context, tx pgx.Tx, classID, competencyID uuid.UUID, code *string, description string, standardID *uuid.UUID) (uuid.UUID, error) {
	description = strings.TrimSpace(description)
	if description == "" {
		return uuid.Nil, db.NewAppError(http.StatusBadRequest, "missing_description",
			"a criterio needs a description: it is what the evidence is judged against")
	}

	// The competency must belong to the class's área. Without this a teacher
	// could hang a criterio off another subject's competency by id.
	var ok bool
	if err := tx.QueryRow(ctx, `
		select exists (
		  select 1 from classes cl
		    join courses co on co.id = cl.course_id
		    join competencies c on c.subject_id = co.subject_id
		   where cl.id = $1 and c.id = $2 and c.deleted_at is null and cl.deleted_at is null
		)
	`, classID, competencyID).Scan(&ok); err != nil {
		return uuid.Nil, err
	}
	if !ok {
		return uuid.Nil, db.NewAppError(http.StatusBadRequest, "competency_not_in_class",
			"that competency does not belong to this class's área")
	}

	var nextOrder int16
	if err := tx.QueryRow(ctx, `
		select coalesce(max(sort_order), 0) + 1 from evaluation_criteria
		 where competency_id = $1 and deleted_at is null
	`, competencyID).Scan(&nextOrder); err != nil {
		return uuid.Nil, err
	}

	var id uuid.UUID
	err := tx.QueryRow(ctx, `
		insert into evaluation_criteria
		  (tenant_id, competency_id, performance_standard_id, code, description, sort_order)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5)
		returning id
	`, competencyID, standardID, code, description, nextOrder).Scan(&id)
	return id, err
}

// DeleteCriterion soft-deletes a criterio. Any levels already recorded
// against it stay on the row, since they are part of a student's academic
// history even once the teacher stops using the criterio.
func DeleteCriterion(ctx context.Context, tx pgx.Tx, criterionID uuid.UUID) error {
	tag, err := tx.Exec(ctx, `
		update evaluation_criteria set deleted_at = now()
		 where id = $1 and deleted_at is null
	`, criterionID)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return db.NewAppError(http.StatusNotFound, "not_found", "criterio not found")
	}
	return nil
}

// AssertCriterionLevel records the level this student reached against one
// criterio, **as read off one piece of evidence**, superseding any level
// already on record for that same pair.
//
// The assessment is required, and that is the whole design. RVM 094-2020
// 5.1.1.3 p.3 determines achievement by valuing evidence *through* the
// criterios; a criterio valued with no evidence in hand inverts that into
// grading the ruler instead of the work. The period-grain shape this function
// used to write is legacy and read-only (see migration 00005).
//
// This is still evidence, not the official record: competency_term_levels is,
// and AssertCompetencyLevel writes it from the teacher's own judgement.
// Nothing rolls these up — the competency level is a judgement over the
// period's evidence, never an average of the cells.
//
// class_id and term_id are not parameters: the trigger
// app.sync_criterion_score_denormalised copies both from the assessment, which
// is also where the draft-assessment and closed-term guards live.
func AssertCriterionLevel(ctx context.Context, tx pgx.Tx, assessmentID, studentID, criterionID, teacherID uuid.UUID, levelCode string, note *string) (uuid.UUID, error) {
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

	// The criterio must be one the evidence actually declares. Without this a
	// level could be filed against a criterio the assessment never set out to
	// show, which is exactly the untraceable judgement the grid exists to
	// prevent.
	var declared bool
	if err := tx.QueryRow(ctx, `
		select exists (
		  select 1 from assessment_criteria
		   where assessment_id = $1 and criterion_id = $2 and deleted_at is null
		)
	`, assessmentID, criterionID).Scan(&declared); err != nil {
		return uuid.Nil, err
	}
	if !declared {
		return uuid.Nil, db.NewAppError(http.StatusBadRequest, "criterion_not_in_evidence",
			"that evidencia does not declare this criterio de evaluación")
	}

	// A per-student piece of evidence belongs to that student alone; levels for
	// anyone else against it would be levels for work they never did.
	var wrongStudent bool
	if err := tx.QueryRow(ctx, `
		select exists (
		  select 1 from assessments
		   where id = $1 and student_id is not null and student_id <> $2
		     and deleted_at is null
		)
	`, assessmentID, studentID).Scan(&wrongStudent); err != nil {
		return uuid.Nil, err
	}
	if wrongStudent {
		return uuid.Nil, db.NewAppError(http.StatusBadRequest, "evidence_not_for_student",
			"that evidencia belongs to a different student")
	}

	var supersedesID *uuid.UUID
	var old uuid.UUID
	err = tx.QueryRow(ctx, `
		update evaluation_criterion_scores set superseded_at = now()
		 where assessment_id = $1 and criterion_id = $2 and student_id = $3
		   and superseded_at is null and deleted_at is null
		returning id
	`, assessmentID, criterionID, studentID).Scan(&old)
	switch err {
	case nil:
		supersedesID = &old
	case pgx.ErrNoRows:
		// First judgement of this criterio on this evidence.
	default:
		return uuid.Nil, err
	}

	var newID uuid.UUID
	err = tx.QueryRow(ctx, `
		insert into evaluation_criterion_scores
		  (tenant_id, assessment_id, criterion_id, student_id, scale_level_id,
		   note, recorded_by_id, supersedes_id)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7)
		returning id
	`, assessmentID, criterionID, studentID, levelID, note, teacherID, supersedesID).Scan(&newID)
	return newID, err
}

// AssessmentCriterionGrid is one piece of evidence with the criterios it
// declares and every student who may be judged against it — the rubric a
// teacher fills in while marking a set of work, rather than one student at a
// time.
type AssessmentCriterionGrid struct {
	AssessmentID uuid.UUID       `json:"assessment_id"`
	Title        string          `json:"title"`
	Kind         string          `json:"kind"`
	ClassID      uuid.UUID       `json:"class_id"`
	TermID       uuid.UUID       `json:"term_id"`
	DueAt        *time.Time      `json:"due_at"`
	IsPersonal   bool            `json:"is_personal"`
	Criteria     []GridCriterion `json:"criteria"`
	Students     []GridStudent   `json:"students"`
}

// GridCriterion is one column header of the grid: a criterio the evidence
// declares, carrying the competencia it belongs to so the teacher can see what
// each column is for.
type GridCriterion struct {
	CriterionID    uuid.UUID `json:"criterion_id"`
	Code           *string   `json:"code"`
	Description    string    `json:"description"`
	CompetencyID   uuid.UUID `json:"competency_id"`
	CompetencyName string    `json:"competency_name"`
}

// GridStudent is one row: the student and their live level per criterio,
// keyed by criterion id. A criterio missing from the map is unjudged — which
// is a real state and must never render as C.
type GridStudent struct {
	StudentID uuid.UUID         `json:"student_id"`
	FullName  string            `json:"full_name"`
	Levels    map[string]string `json:"levels"`
}

// GetAssessmentCriterionGrid loads the evidencia × criterio grid for one piece
// of evidence across its whole roster.
//
// There is no mark in this response on purpose. This screen is the official
// reading — evidence judged against criterios — and the school's numeric
// system is the other reading, captured on the student's own screen. Putting a
// /20 box next to these pickers would put a number in the teacher's eye at the
// moment they are supposed to be judging against a criterio.
func GetAssessmentCriterionGrid(ctx context.Context, tx pgx.Tx, assessmentID uuid.UUID) (AssessmentCriterionGrid, error) {
	var g AssessmentCriterionGrid
	g.AssessmentID = assessmentID
	var onlyStudent *uuid.UUID
	err := tx.QueryRow(ctx, `
		select a.title, a.kind, a.class_id, a.term_id, a.due_at, a.student_id
		  from assessments a
		 where a.id = $1 and a.deleted_at is null
	`, assessmentID).Scan(&g.Title, &g.Kind, &g.ClassID, &g.TermID, &g.DueAt, &onlyStudent)
	if err != nil {
		if err == pgx.ErrNoRows {
			return g, db.NewAppError(http.StatusNotFound, "not_found", "evidencia not found")
		}
		return g, err
	}
	g.IsPersonal = onlyStudent != nil
	g.Criteria = []GridCriterion{}
	g.Students = []GridStudent{}

	asOf := time.Now()
	if g.DueAt != nil {
		asOf = *g.DueAt
	}

	crows, err := tx.Query(ctx, `
		select ec.id, ec.code, ec.description, c.id, c.name
		  from assessment_criteria ac
		  join evaluation_criteria ec on ec.id = ac.criterion_id and ec.deleted_at is null
		  join competencies c on c.id = ec.competency_id
		 where ac.assessment_id = $1 and ac.deleted_at is null
		 order by c.sort_order, c.code, ec.sort_order nulls last, ec.code nulls last
	`, assessmentID)
	if err != nil {
		return g, err
	}
	for crows.Next() {
		var gc GridCriterion
		if err := crows.Scan(&gc.CriterionID, &gc.Code, &gc.Description,
			&gc.CompetencyID, &gc.CompetencyName); err != nil {
			crows.Close()
			return g, err
		}
		g.Criteria = append(g.Criteria, gc)
	}
	crows.Close()
	if err := crows.Err(); err != nil {
		return g, err
	}

	// Personal evidence narrows the grid to its one student; class-wide
	// evidence takes the canonical roster-as-of join (the same one RosterAsOf
	// and GetSessionRoster use) as of the due date, so a student who left
	// afterwards still appears against work they actually did. Evidence with no
	// due date falls back to today, which is what the roster means when the
	// teacher is marking right now.
	srows, err := tx.Query(ctx, `
		select st.id,
		       coalesce(st.preferred_name, st.given_name) || ' ' || st.paternal_surname as name,
		       coalesce(
		         jsonb_object_agg(ecs.criterion_id::text, l.code)
		           filter (where ecs.id is not null),
		         '{}'::jsonb)
		  from section_memberships sm
		  join classes c on c.section_id = sm.section_id and c.id = $2
		  join students st on st.id = sm.student_id and st.deleted_at is null
		  left join evaluation_criterion_scores ecs
		         on ecs.assessment_id = $1 and ecs.student_id = st.id
		        and ecs.superseded_at is null and ecs.deleted_at is null
		  left join grade_scale_levels l on l.id = ecs.scale_level_id
		 where sm.joined_on <= $4 and (sm.left_on is null or sm.left_on > $4)
		   and sm.deleted_at is null
		   and ($3::uuid is null or st.id = $3::uuid)
		 group by st.id, name, st.paternal_surname, st.given_name
		 order by st.paternal_surname, st.given_name
	`, assessmentID, g.ClassID, onlyStudent, asOf)
	if err != nil {
		return g, err
	}
	defer srows.Close()
	for srows.Next() {
		var gs GridStudent
		if err := srows.Scan(&gs.StudentID, &gs.FullName, &gs.Levels); err != nil {
			return g, err
		}
		g.Students = append(g.Students, gs)
	}
	return g, srows.Err()
}
