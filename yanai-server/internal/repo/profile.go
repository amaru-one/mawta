package repo

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type ProfileClass struct {
	ClassID      uuid.UUID `json:"class_id"`
	Name         string    `json:"name"`
	RosterCount  int       `json:"roster_count"`
	SlotsPerWeek int       `json:"slots_per_week"`
}

type ProfileGradeGroup struct {
	GradeLabel string         `json:"grade_label"`
	Classes    []ProfileClass `json:"classes"`
}

type ProfileTopStats struct {
	ClassesCount  int     `json:"classes"`
	StudentsCount int     `json:"students"`
	WeeklyHours   float64 `json:"weekly_hours"`
}

type ProfileActivity struct {
	ClasesDictadas         int `json:"clases_dictadas"`
	AsistenciasRegistradas int `json:"asistencias_registradas"`
	AsistenciasEsperadas   int `json:"asistencias_esperadas"`
	NotasDeVoz             int `json:"notas_de_voz"`
	Evaluaciones           int `json:"evaluaciones"`
	AlumnosEnSeguimiento   int `json:"alumnos_en_seguimiento"`
}

type ProfileResponse struct {
	DisplayName string              `json:"display_name"`
	Title       *string             `json:"title"`
	HiredOn     *time.Time          `json:"hired_on"`
	TenantName  string              `json:"tenant_name"`
	TenantCity  *string             `json:"tenant_city"`
	TopStats    ProfileTopStats     `json:"top_stats"`
	Activity    ProfileActivity     `json:"activity"`
	Classes     []ProfileGradeGroup `json:"classes_by_grade"`
}

func GetProfile(ctx context.Context, tx pgx.Tx, teacherID uuid.UUID, term Term, today time.Time) (ProfileResponse, error) {
	var resp ProfileResponse

	err := tx.QueryRow(ctx, `
		select t.display_name, t.title, t.hired_on, tn.name, tn.city
		  from teachers t join tenants tn on tn.id = t.tenant_id
		 where t.id = $1
	`, teacherID).Scan(&resp.DisplayName, &resp.Title, &resp.HiredOn, &resp.TenantName, &resp.TenantCity)
	if err != nil {
		return resp, err
	}

	rows, err := tx.Query(ctx, `
		select distinct c.id, c.name, sec.id, gl.long_label, gl.ordinal
		  from class_teachers ct
		  join classes c on c.id = ct.class_id and c.deleted_at is null and c.status = 'active'
		  join sections sec on sec.id = c.section_id
		  join grade_levels gl on gl.id = sec.grade_level_id
		 where ct.teacher_id = $1 and ct.starts_on <= $2
		   and (ct.ends_on is null or ct.ends_on >= $2) and ct.deleted_at is null
		 order by gl.ordinal, c.name
	`, teacherID, today)
	if err != nil {
		return resp, err
	}

	type classRow struct {
		id, sectionID    uuid.UUID
		name, gradeLabel string
		ordinal          int
	}
	var classRows []classRow
	for rows.Next() {
		var cr classRow
		if err := rows.Scan(&cr.id, &cr.name, &cr.sectionID, &cr.gradeLabel, &cr.ordinal); err != nil {
			rows.Close()
			return resp, err
		}
		classRows = append(classRows, cr)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return resp, err
	}

	if len(classRows) == 0 {
		return resp, nil
	}

	classIDs := make([]uuid.UUID, len(classRows))
	sectionIDs := make([]uuid.UUID, len(classRows))
	for i, cr := range classRows {
		classIDs[i] = cr.id
		sectionIDs[i] = cr.sectionID
	}
	resp.TopStats.ClassesCount = len(classRows)

	if err := tx.QueryRow(ctx, `
		select count(distinct sm.student_id) from section_memberships sm
		 where sm.section_id = any($1::uuid[])
		   and sm.joined_on <= $2 and (sm.left_on is null or sm.left_on > $2) and sm.deleted_at is null
	`, sectionIDs, today).Scan(&resp.TopStats.StudentsCount); err != nil {
		return resp, err
	}

	if err := tx.QueryRow(ctx, `
		select coalesce(sum(extract(epoch from (ends_at - starts_at)) / 3600.0), 0)
		  from class_schedules
		 where class_id = any($1::uuid[]) and effective_from <= $2
		   and (effective_to is null or effective_to > $2) and deleted_at is null
	`, classIDs, today).Scan(&resp.TopStats.WeeklyHours); err != nil {
		return resp, err
	}

	if term.ID != uuid.Nil {
		if err := tx.QueryRow(ctx, `
			select count(*) from class_sessions
			 where class_id = any($1::uuid[]) and term_id = $2 and status = 'completed' and deleted_at is null
		`, classIDs, term.ID).Scan(&resp.Activity.ClasesDictadas); err != nil {
			return resp, err
		}
		if err := tx.QueryRow(ctx, `
			select count(*) filter (where attendance_taken_at is not null), count(*)
			  from class_sessions
			 where class_id = any($1::uuid[]) and term_id = $2 and status = 'completed' and deleted_at is null
		`, classIDs, term.ID).Scan(&resp.Activity.AsistenciasRegistradas, &resp.Activity.AsistenciasEsperadas); err != nil {
			return resp, err
		}
		if err := tx.QueryRow(ctx, `
			select count(*) from voice_notes
			 where teacher_id = $1 and recorded_at::date between $2 and $3 and deleted_at is null
		`, teacherID, term.StartsOn, term.EndsOn).Scan(&resp.Activity.NotasDeVoz); err != nil {
			return resp, err
		}
		if err := tx.QueryRow(ctx, `
			select count(*) from assessments
			 where created_by_id = $1 and term_id = $2 and deleted_at is null
		`, teacherID, term.ID).Scan(&resp.Activity.Evaluaciones); err != nil {
			return resp, err
		}
		if err := tx.QueryRow(ctx, `
			select count(distinct student_id) from risk_flags
			 where class_id = any($1::uuid[]) and status = 'active' and deleted_at is null
		`, classIDs).Scan(&resp.Activity.AlumnosEnSeguimiento); err != nil {
			return resp, err
		}
	}

	groupsByLabel := make(map[string]*ProfileGradeGroup)
	var order []string
	for _, cr := range classRows {
		roster, err := RosterAsOf(ctx, tx, cr.id, today)
		if err != nil {
			return resp, err
		}
		var slots int
		if err := tx.QueryRow(ctx, `
			select count(*) from class_schedules
			 where class_id = $1 and effective_from <= $2
			   and (effective_to is null or effective_to > $2) and deleted_at is null
		`, cr.id, today).Scan(&slots); err != nil {
			return resp, err
		}
		g, ok := groupsByLabel[cr.gradeLabel]
		if !ok {
			g = &ProfileGradeGroup{GradeLabel: cr.gradeLabel}
			groupsByLabel[cr.gradeLabel] = g
			order = append(order, cr.gradeLabel)
		}
		g.Classes = append(g.Classes, ProfileClass{
			ClassID: cr.id, Name: cr.name, RosterCount: len(roster), SlotsPerWeek: slots,
		})
	}
	for _, label := range order {
		resp.Classes = append(resp.Classes, *groupsByLabel[label])
	}

	return resp, nil
}
