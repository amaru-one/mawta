package repo

import (
	"context"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// What the SIAGIE receives at the end of a period, for one class.
//
// RVM 048-2024 num. 5.1.2.2: per student, the nivel de logro of each
// competencia *developed and explicitly evaluated in the period*, plus a
// conclusión descriptiva wherever one is mandatory. Competencies not worked
// simply have no value — the report leaves them null rather than defaulting to
// C, because absence and "en inicio" are different facts.
//
// Nothing here reports a level for the área itself: "no se asignará un nivel
// de logro a cada área curricular" (5.1.1.3 p.12).
type SiagieReport struct {
	ClassID        uuid.UUID `json:"class_id"`
	ClassName      string    `json:"class_name"`
	SubjectCode    string    `json:"subject_code"`
	AreaCurricular *string   `json:"area_curricular"`
	TermID         uuid.UUID `json:"term_id"`
	TermName       string    `json:"term_name"`
	TermSequence   int16     `json:"term_sequence"`
	// Students carry one entry per competency of the área, in curriculum order.
	Students []SiagieStudent `json:"students"`
	// Blocking lists the mandatory conclusiones descriptivas still missing.
	// While it is non-empty the period is not ready to be sent.
	Blocking []MissingConclusion `json:"blocking"`
	Ready    bool                `json:"ready"`
	// Notice is shown verbatim above the table.
	Notice string `json:"notice"`
}

type SiagieStudent struct {
	StudentID    uuid.UUID          `json:"student_id"`
	StudentCode  string             `json:"student_code"`
	StudentName  string             `json:"student_name"`
	Competencies []SiagieCompetency `json:"competencies"`
}

type SiagieCompetency struct {
	CompetencyID uuid.UUID `json:"competency_id"`
	Code         string    `json:"code"`
	Name         string    `json:"name"`
	// Level is null when the competency was not worked this period.
	Level      *string `json:"level"`
	Conclusion *string `json:"conclusion"`
	// ConclusionRequired mirrors the norm's obligation for this row.
	ConclusionRequired bool `json:"conclusion_required"`
}

const siagieNotice = "Niveles de logro por competencia (RVM 094-2020, modificada por RVM 048-2024). " +
	"Una competencia sin valor no fue desarrollada ni evaluada en el periodo; no equivale a C. " +
	"El calificativo numérico por área lo calcula el SIAGIE, no este reporte."

// GetSiagieReport builds the end-of-period report for one class and term.
func GetSiagieReport(ctx context.Context, tx pgx.Tx, classID, termID uuid.UUID) (SiagieReport, error) {
	var rep SiagieReport
	rep.ClassID = classID
	rep.TermID = termID
	rep.Notice = siagieNotice

	err := tx.QueryRow(ctx, `
		select cl.name, sub.code, sub.area_curricular, t.name, t.sequence
		  from classes cl
		  join courses co on co.id = cl.course_id
		  join subjects sub on sub.id = co.subject_id
		  join terms t on t.id = $2
		 where cl.id = $1
	`, classID, termID).Scan(&rep.ClassName, &rep.SubjectCode, &rep.AreaCurricular,
		&rep.TermName, &rep.TermSequence)
	if err != nil {
		return rep, err
	}

	// One row per (student in the class's section during the term) ×
	// (competency of the área), so a competency with no level still appears —
	// visibly blank, which is the point.
	rows, err := tx.Query(ctx, `
		with roster as (
		  select distinct s.id, s.student_code,
		         trim(s.given_name || ' ' || s.paternal_surname
		              || coalesce(' ' || s.maternal_surname, '')) as full_name
		    from classes cl
		    join section_memberships sm on sm.section_id = cl.section_id
		                               and sm.academic_year_id = cl.academic_year_id
		    join students s on s.id = sm.student_id
		   where cl.id = $1 and sm.deleted_at is null and s.deleted_at is null
		),
		comps as (
		  select c.id, c.code, c.name, c.sort_order
		    from classes cl
		    join courses co on co.id = cl.course_id
		    join competencies c on c.subject_id = co.subject_id
		   where cl.id = $1 and c.is_active and c.deleted_at is null
		)
		select r.id, r.student_code, r.full_name,
		       cp.id, cp.code, cp.name,
		       l.code,
		       dc.body,
		       (l.code = 'C' or st.inclusion_support)
		  from roster r
		  join students st on st.id = r.id
		  cross join comps cp
		  left join competency_term_levels ctl
		         on ctl.student_id = r.id and ctl.competency_id = cp.id
		        and ctl.term_id = $2
		        and ctl.superseded_at is null and ctl.deleted_at is null
		  left join grade_scale_levels l on l.id = ctl.scale_level_id
		  left join descriptive_conclusions dc
		         on dc.student_id = r.id and dc.competency_id = cp.id
		        and dc.term_id = $2 and dc.status = 'final'
		        and dc.superseded_at is null and dc.deleted_at is null
		 order by r.full_name, cp.sort_order, cp.code
	`, classID, termID)
	if err != nil {
		return rep, err
	}
	defer rows.Close()

	byStudent := map[uuid.UUID]int{}
	for rows.Next() {
		var studentID, competencyID uuid.UUID
		var studentCode, studentName, code, name string
		var level, conclusion *string
		var required *bool
		if err := rows.Scan(&studentID, &studentCode, &studentName,
			&competencyID, &code, &name, &level, &conclusion, &required); err != nil {
			return rep, err
		}
		idx, seen := byStudent[studentID]
		if !seen {
			rep.Students = append(rep.Students, SiagieStudent{
				StudentID: studentID, StudentCode: studentCode, StudentName: studentName,
			})
			idx = len(rep.Students) - 1
			byStudent[studentID] = idx
		}
		rep.Students[idx].Competencies = append(rep.Students[idx].Competencies, SiagieCompetency{
			CompetencyID:       competencyID,
			Code:               code,
			Name:               name,
			Level:              level,
			Conclusion:         conclusion,
			ConclusionRequired: required != nil && *required,
		})
	}
	if err := rows.Err(); err != nil {
		return rep, err
	}

	blocking, err := MissingMandatoryConclusions(ctx, tx, classID, termID)
	if err != nil {
		return rep, err
	}
	rep.Blocking = blocking
	rep.Ready = len(blocking) == 0
	return rep, nil
}
