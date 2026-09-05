package repo

import (
	"context"
	"net/http"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/db"
)

// CriterionRow is one criterio de evaluación: the teacher's own precisado of
// what they will judge a competencia against, optionally anchored to a CNEB
// desempeño (performance_standards).
//
// It carries no level, and must not grow one. A criterio says what to look at
// in a piece of work — it is the ruler, never the thing marked. The one
// judgement this app records is the nivel de logro of a competencia
// (competency_term_levels), asserted by the teacher after reading the period's
// evidence (RVM 094-2020, 5.1.1.3 p.2-3).
type CriterionRow struct {
	CriterionID uuid.UUID  `json:"criterion_id"`
	Code        *string    `json:"code"`
	Description string     `json:"description"`
	SortOrder   int16      `json:"sort_order"`
	StandardID  *uuid.UUID `json:"performance_standard_id"`
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
// criterios. It is not scoped to a student and has no reason to be: nothing
// here is per-student any more.
func ListClassCriteria(ctx context.Context, tx pgx.Tx, classID uuid.UUID) ([]CompetencyCriteriaRow, error) {
	rows, err := tx.Query(ctx, `
		with cls as (
		  select co.subject_id
		    from classes cl
		    join courses co on co.id = cl.course_id
		   where cl.id = $1 and cl.deleted_at is null
		)
		select c.id, c.code, c.name, c.kind,
		       ec.id, ec.code, ec.description, ec.sort_order, ec.performance_standard_id
		  from competencies c
		  left join evaluation_criteria ec
		         on ec.competency_id = c.id and ec.is_active and ec.deleted_at is null
		 where c.subject_id = (select subject_id from cls)
		   and c.is_active and c.deleted_at is null
		 order by c.sort_order, c.code, ec.sort_order nulls last, ec.code nulls last
	`, classID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []CompetencyCriteriaRow
	byCompetency := make(map[uuid.UUID]int)
	for rows.Next() {
		var comp CompetencyCriteriaRow
		var crit CriterionRow
		// A competencia with no criterios still produces a row (left join), so
		// every criterio column arrives null and has to be scanned as such.
		var critID *uuid.UUID
		var sortOrder *int16
		var description *string
		if err := rows.Scan(&comp.CompetencyID, &comp.Code, &comp.Name, &comp.Kind,
			&critID, &crit.Code, &description, &sortOrder, &crit.StandardID); err != nil {
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
			out[idx].Criteria = append(out[idx].Criteria, crit)
		}
	}
	return out, rows.Err()
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

// DeleteCriterion soft-deletes a criterio. Evidence already tagged with it
// keeps the tag, since what a teacher set out to look at in a piece of work is
// part of that work's record even once the criterio stops being used.
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
