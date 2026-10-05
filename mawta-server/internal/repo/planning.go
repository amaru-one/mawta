package repo

import (
	"context"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/db"
)

// Term planning (docs/api-planificacion.md): a teacher plans one class's term
// as learning experiences, each with competencies, criteria, planned
// evidences and a light session outline.
//
// Two rules hold across this file:
//
//   - A class date is a date with a non-cancelled class_sessions row of the
//     class that is not a non_teaching_days day. A double block is one date.
//   - Something Mawta proposed only counts once the teacher accepted or
//     edited it: coverage and "capability without criterion" look at
//     accepted_at, so a pending proposal never reads as planned work.
//
// Only the class's área competencies take part. The schema has no way to
// assign a transversal competency to a class, and check_competency_subject
// (00002) only links competencies of the class's área to an experience.

// dateLayout is how every planning date travels: YYYY-MM-DD.
const dateLayout = "2006-01-02"

// classContext is what the planning reads need to know about a class.
type classContext struct {
	SubjectID    uuid.UUID
	GradeLevelID uuid.UUID
	YearID       uuid.UUID
	GradeCode    string
	Stage        string
	Cycle        *string
}

func loadClassContext(ctx context.Context, tx pgx.Tx, classID uuid.UUID) (classContext, error) {
	var c classContext
	err := tx.QueryRow(ctx, `
		select co.subject_id, co.grade_level_id, cl.academic_year_id, gl.code, gl.stage, gl.cycle
		  from classes cl
		  join courses co on co.id = cl.course_id
		  join grade_levels gl on gl.id = co.grade_level_id
		 where cl.id = $1 and cl.deleted_at is null
	`, classID).Scan(&c.SubjectID, &c.GradeLevelID, &c.YearID, &c.GradeCode, &c.Stage, &c.Cycle)
	return c, err
}

// classDatesSQL selects the class dates of class $1 between $2 and $3.
const classDatesSQL = `
	select distinct cs.session_date
	  from class_sessions cs
	 where cs.class_id = $1
	   and cs.deleted_at is null
	   and cs.status <> 'cancelled'
	   and cs.session_date between $2 and $3
	   and not exists (
	     select 1 from non_teaching_days n
	      where n.tenant_id = cs.tenant_id
	        and n.academic_year_id = cs.academic_year_id
	        and n.day = cs.session_date
	        and n.deleted_at is null
	   )`

// ClassDates returns the class dates of a class in [from, to], in order.
func ClassDates(ctx context.Context, tx pgx.Tx, classID uuid.UUID, from, to time.Time) ([]string, error) {
	rows, err := tx.Query(ctx, `
		select to_char(d.session_date, 'YYYY-MM-DD') from (`+classDatesSQL+`) d
		 order by d.session_date
	`, classID, from, to)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var d string
		if err := rows.Scan(&d); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

func countClassDates(ctx context.Context, tx pgx.Tx, classID uuid.UUID, from, to time.Time) (int, error) {
	var n int
	err := tx.QueryRow(ctx, `select count(*) from (`+classDatesSQL+`) d`, classID, from, to).Scan(&n)
	return n, err
}

// ------------------------------------------------------------------ plan --

type PlanTerm struct {
	ID       uuid.UUID `json:"id"`
	Name     string    `json:"name"`
	StartsOn string    `json:"starts_on"`
	EndsOn   string    `json:"ends_on"`
	Status   string    `json:"status"`

	sequence int16
	from, to time.Time
}

// NonTeachingRange is a run of consecutive non-teaching days of one kind and
// label, e.g. a two-week vacation.
type NonTeachingRange struct {
	From  string  `json:"from"`
	To    string  `json:"to"`
	Kind  string  `json:"kind"`
	Label *string `json:"label"`
}

type PlanExperienceCompetency struct {
	ID                       uuid.UUID `json:"id"`
	Code                     string    `json:"code"`
	Name                     string    `json:"name"`
	CapabilitiesTotal        int       `json:"capabilities_total"`
	CapabilitiesWithCriteria int       `json:"capabilities_with_criteria"`
}

type PlanExperience struct {
	ID               uuid.UUID                  `json:"id"`
	Title            string                     `json:"title"`
	Status           string                     `json:"status"`
	StartsOn         string                     `json:"starts_on"`
	EndsOn           string                     `json:"ends_on"`
	ClassDates       int                        `json:"class_dates"`
	Competencies     []PlanExperienceCompetency `json:"competencies"`
	PendingProposals int                        `json:"pending_proposals"`

	from, to time.Time
}

// PlanCompetency is one competency's standing in the term. Status is
// computed on every read; there is no stored summary (decision 9 of the
// flow).
type PlanCompetency struct {
	ID                          uuid.UUID `json:"id"`
	Code                        string    `json:"code"`
	Name                        string    `json:"name"`
	Status                      string    `json:"status"`
	TermsWorked                 []int32   `json:"terms_worked"`
	CapabilitiesTotal           int       `json:"capabilities_total"`
	CapabilitiesCoveredThisTerm int       `json:"capabilities_covered_this_term"`
}

type Plan struct {
	Term            PlanTerm           `json:"term"`
	NonTeachingDays []NonTeachingRange `json:"non_teaching_days"`
	ClassDatesTotal int                `json:"class_dates_total"`
	Experiences     []PlanExperience   `json:"experiences"`
	Competencies    []PlanCompetency   `json:"competencies"`
}

// ResolvePlanTerm picks the term "Tu trimestre" shows: termID when given
// (it must be a term of the class's year), else the term containing today,
// else the next one, else the last one. Terms of another stage are skipped.
//
// This is not ResolveTerm: onboarding leaves every term 'active', so "the
// active term" says nothing about which one the teacher is living in.
func ResolvePlanTerm(ctx context.Context, tx pgx.Tx, classID, termID uuid.UUID, today time.Time) (PlanTerm, error) {
	cc, err := loadClassContext(ctx, tx, classID)
	if err != nil {
		return PlanTerm{}, err
	}
	var t PlanTerm
	err = tx.QueryRow(ctx, `
		select id, name, starts_on, ends_on, status, sequence
		  from terms
		 where academic_year_id = $1
		   and deleted_at is null
		   and (stage is null or stage = $2)
		   and ($3::uuid is null or id = $3)
		 order by case when $4::date between starts_on and ends_on then 0
		               when starts_on > $4::date then 1
		               else 2 end,
		          case when starts_on > $4::date then starts_on end,
		          ends_on desc
		 limit 1
	`, cc.YearID, cc.Stage, nullUUID(termID), today).Scan(&t.ID, &t.Name, &t.from, &t.to, &t.Status, &t.sequence)
	if err != nil {
		if err == pgx.ErrNoRows {
			return t, db.NewAppError(http.StatusNotFound, "not_found", "no se encontró el periodo")
		}
		return t, err
	}
	t.StartsOn, t.EndsOn = t.from.Format(dateLayout), t.to.Format(dateLayout)
	return t, nil
}

func nullUUID(id uuid.UUID) *uuid.UUID {
	if id == uuid.Nil {
		return nil
	}
	return &id
}

// GetPlan builds "Tu trimestre" for one class and term.
func GetPlan(ctx context.Context, tx pgx.Tx, classID uuid.UUID, term PlanTerm) (Plan, error) {
	cc, err := loadClassContext(ctx, tx, classID)
	if err != nil {
		return Plan{}, err
	}
	p := Plan{Term: term}

	if p.NonTeachingDays, err = nonTeachingRanges(ctx, tx, cc.YearID, term.from, term.to); err != nil {
		return p, err
	}
	if p.ClassDatesTotal, err = countClassDates(ctx, tx, classID, term.from, term.to); err != nil {
		return p, err
	}
	if p.Experiences, err = planExperiences(ctx, tx, classID, term.ID); err != nil {
		return p, err
	}
	p.Competencies, err = planCompetencies(ctx, tx, classID, cc, term)
	return p, err
}

// nonTeachingRanges groups the non-teaching days in [from, to] into runs of
// consecutive days with the same kind and label (gaps and islands: day minus
// its row number is constant inside a run).
func nonTeachingRanges(ctx context.Context, tx pgx.Tx, yearID uuid.UUID, from, to time.Time) ([]NonTeachingRange, error) {
	rows, err := tx.Query(ctx, `
		select to_char(min(day), 'YYYY-MM-DD'), to_char(max(day), 'YYYY-MM-DD'), kind, label
		  from (
		    select day, kind, label,
		           day - (row_number() over (partition by kind, coalesce(label, '') order by day))::int as grp
		      from non_teaching_days
		     where academic_year_id = $1 and deleted_at is null and day between $2 and $3
		  ) s
		 group by kind, label, grp
		 order by min(day)
	`, yearID, from, to)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []NonTeachingRange{}
	for rows.Next() {
		var r NonTeachingRange
		if err := rows.Scan(&r.From, &r.To, &r.Kind, &r.Label); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func planExperiences(ctx context.Context, tx pgx.Tx, classID, termID uuid.UUID) ([]PlanExperience, error) {
	rows, err := tx.Query(ctx, `
		select le.id, le.title, le.status, le.starts_on, le.ends_on,
		       (select count(*) from evaluation_criteria cr
		         where cr.experience_id = le.id and cr.deleted_at is null and cr.accepted_at is null)
		     + (select count(*) from planned_evidences pe
		         where pe.experience_id = le.id and pe.deleted_at is null and pe.accepted_at is null)
		     + (select count(*) from session_outline_entries se
		         where se.experience_id = le.id and se.deleted_at is null and se.accepted_at is null)
		  from learning_experiences le
		 where le.class_id = $1 and le.term_id = $2 and le.deleted_at is null
		 order by le.starts_on
	`, classID, termID)
	if err != nil {
		return nil, err
	}
	out := []PlanExperience{}
	for rows.Next() {
		var e PlanExperience
		if err := rows.Scan(&e.ID, &e.Title, &e.Status, &e.from, &e.to, &e.PendingProposals); err != nil {
			rows.Close()
			return nil, err
		}
		e.StartsOn, e.EndsOn = e.from.Format(dateLayout), e.to.Format(dateLayout)
		out = append(out, e)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}

	for i := range out {
		e := &out[i]
		if e.ClassDates, err = countClassDates(ctx, tx, classID, e.from, e.to); err != nil {
			return nil, err
		}
		if e.Competencies, err = experienceCoverage(ctx, tx, e.ID); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// experienceCoverage lists an experience's competencies with how many of
// their capabilities an accepted criterion of the experience looks at.
func experienceCoverage(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID) ([]PlanExperienceCompetency, error) {
	rows, err := tx.Query(ctx, `
		select c.id, c.code, c.name,
		       (select count(*) from capabilities cap
		         where cap.competency_id = c.id and cap.is_active and cap.deleted_at is null),
		       (select count(distinct x.capability_id)
		          from evaluation_criteria cr
		          join evaluation_criterion_capabilities x on x.criterion_id = cr.id and x.deleted_at is null
		         where cr.experience_id = ec.experience_id and cr.competency_id = c.id
		           and cr.deleted_at is null and cr.accepted_at is not null)
		  from experience_competencies ec
		  join competencies c on c.id = ec.competency_id
		 where ec.experience_id = $1 and ec.deleted_at is null
		 order by c.sort_order, c.code
	`, experienceID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []PlanExperienceCompetency{}
	for rows.Next() {
		var c PlanExperienceCompetency
		if err := rows.Scan(&c.ID, &c.Code, &c.Name, &c.CapabilitiesTotal, &c.CapabilitiesWithCriteria); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// planCompetencies applies the contract's tracking rule to every competency
// of the class's área:
//
//   - planificada: a non-deleted experience of this class in this term works it;
//   - toca: otherwise, when it still needs terms to reach two worked terms in
//     the year and the terms left (this one included) are no more than it needs;
//   - puede_esperar: otherwise.
//
// A worked term is a term of the year with a non-deleted experience of this
// class working the competency, drafts included.
func planCompetencies(ctx context.Context, tx pgx.Tx, classID uuid.UUID, cc classContext, term PlanTerm) ([]PlanCompetency, error) {
	rows, err := tx.Query(ctx, `
		with worked as (
		  select ec.competency_id,
		         array_agg(distinct t.sequence::int order by t.sequence::int) as seqs,
		         bool_or(le.term_id = $3) as this_term
		    from learning_experiences le
		    join experience_competencies ec on ec.experience_id = le.id and ec.deleted_at is null
		    join terms t on t.id = le.term_id
		   where le.class_id = $1 and le.academic_year_id = $4 and le.deleted_at is null
		   group by ec.competency_id
		),
		terms_left as (
		  select count(*)::int as n
		    from terms
		   where academic_year_id = $4 and deleted_at is null
		     and (stage is null or stage = $5)
		     and sequence >= $6
		),
		covered as (
		  select cr.competency_id, count(distinct x.capability_id)::int as n
		    from learning_experiences le
		    join evaluation_criteria cr on cr.experience_id = le.id
		         and cr.deleted_at is null and cr.accepted_at is not null
		    join evaluation_criterion_capabilities x on x.criterion_id = cr.id and x.deleted_at is null
		   where le.class_id = $1 and le.term_id = $3 and le.deleted_at is null
		   group by cr.competency_id
		)
		select c.id, c.code, c.name,
		       case
		         when coalesce(w.this_term, false) then 'planificada'
		         when greatest(0, 2 - coalesce(cardinality(w.seqs), 0)) > 0
		          and (select n from terms_left) <= greatest(0, 2 - coalesce(cardinality(w.seqs), 0))
		           then 'toca'
		         else 'puede_esperar'
		       end,
		       coalesce(w.seqs, '{}'),
		       (select count(*)::int from capabilities cap
		         where cap.competency_id = c.id and cap.is_active and cap.deleted_at is null),
		       coalesce(cv.n, 0)
		  from competencies c
		  left join worked w on w.competency_id = c.id
		  left join covered cv on cv.competency_id = c.id
		 where c.subject_id = $2 and c.is_active and c.deleted_at is null
		 order by c.sort_order, c.code
	`, classID, cc.SubjectID, term.ID, cc.YearID, cc.Stage, term.sequence)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []PlanCompetency{}
	for rows.Next() {
		var c PlanCompetency
		if err := rows.Scan(&c.ID, &c.Code, &c.Name, &c.Status, &c.TermsWorked,
			&c.CapabilitiesTotal, &c.CapabilitiesCoveredThisTerm); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// ------------------------------------------------------------ curriculum --

type CurriculumGrade struct {
	Code          string  `json:"code"`
	Cycle         *string `json:"cycle"`
	ExpectedLevel *int16  `json:"expected_level"`
}

type CurriculumCapability struct {
	ID   uuid.UUID `json:"id"`
	Code string    `json:"code"`
	Name string    `json:"name"`
}

type CurriculumPerformance struct {
	ID                    uuid.UUID  `json:"id"`
	Order                 int16      `json:"order"`
	Text                  string     `json:"text"`
	EnProceso             bool       `json:"en_proceso"`
	SuggestedCapabilityID *uuid.UUID `json:"suggested_capability_id"`
}

type CurriculumCompetency struct {
	ID           uuid.UUID               `json:"id"`
	Code         string                  `json:"code"`
	Name         string                  `json:"name"`
	Kind         string                  `json:"kind"`
	Capabilities []CurriculumCapability  `json:"capabilities"`
	Performances []CurriculumPerformance `json:"performances"`
}

type Curriculum struct {
	Grade        CurriculumGrade        `json:"grade"`
	Competencies []CurriculumCompetency `json:"competencies"`
}

// GetCurriculum returns the competencies of the class's área with their
// capabilities and the performances of the class's grade. No standards: they
// are not a source of criteria (decision 5 of the contract).
func GetCurriculum(ctx context.Context, tx pgx.Tx, classID uuid.UUID) (Curriculum, error) {
	cc, err := loadClassContext(ctx, tx, classID)
	if err != nil {
		return Curriculum{}, err
	}
	out := Curriculum{Grade: CurriculumGrade{Code: cc.GradeCode, Cycle: cc.Cycle}, Competencies: []CurriculumCompetency{}}
	if cc.Cycle != nil {
		var level int16
		err := tx.QueryRow(ctx, `
			select expected_level from standard_level_mappings
			 where modality = 'ebr' and cycle = $1 and deleted_at is null
		`, *cc.Cycle).Scan(&level)
		switch err {
		case nil:
			out.Grade.ExpectedLevel = &level
		case pgx.ErrNoRows:
		default:
			return out, err
		}
	}

	rows, err := tx.Query(ctx, `
		select id, code, name, kind from competencies
		 where subject_id = $1 and is_active and deleted_at is null
		 order by sort_order, code
	`, cc.SubjectID)
	if err != nil {
		return out, err
	}
	index := map[uuid.UUID]int{}
	for rows.Next() {
		c := CurriculumCompetency{Capabilities: []CurriculumCapability{}, Performances: []CurriculumPerformance{}}
		if err := rows.Scan(&c.ID, &c.Code, &c.Name, &c.Kind); err != nil {
			rows.Close()
			return out, err
		}
		index[c.ID] = len(out.Competencies)
		out.Competencies = append(out.Competencies, c)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return out, err
	}

	rows, err = tx.Query(ctx, `
		select cap.competency_id, cap.id, cap.code, cap.name
		  from capabilities cap
		  join competencies c on c.id = cap.competency_id
		 where c.subject_id = $1 and cap.is_active and cap.deleted_at is null
		 order by cap.sort_order, cap.code
	`, cc.SubjectID)
	if err != nil {
		return out, err
	}
	for rows.Next() {
		var compID uuid.UUID
		var cap CurriculumCapability
		if err := rows.Scan(&compID, &cap.ID, &cap.Code, &cap.Name); err != nil {
			rows.Close()
			return out, err
		}
		if i, ok := index[compID]; ok {
			out.Competencies[i].Capabilities = append(out.Competencies[i].Capabilities, cap)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return out, err
	}

	rows, err = tx.Query(ctx, `
		select p.competency_id, p.id, p.sort_order, p.official_text, p.en_proceso, p.suggested_capability_id
		  from grade_level_performances p
		  join competencies c on c.id = p.competency_id
		 where c.subject_id = $1 and p.grade_level_id = $2 and p.deleted_at is null
		 order by p.sort_order
	`, cc.SubjectID, cc.GradeLevelID)
	if err != nil {
		return out, err
	}
	defer rows.Close()
	for rows.Next() {
		var compID uuid.UUID
		var p CurriculumPerformance
		if err := rows.Scan(&compID, &p.ID, &p.Order, &p.Text, &p.EnProceso, &p.SuggestedCapabilityID); err != nil {
			return out, err
		}
		if i, ok := index[compID]; ok {
			out.Competencies[i].Performances = append(out.Competencies[i].Performances, p)
		}
	}
	return out, rows.Err()
}

// -------------------------------------------------------------- calendar --

type CalendarDay struct {
	Date  string  `json:"date"`
	Kind  string  `json:"kind"`
	Label *string `json:"label"`
}

type Calendar struct {
	ClassDates      []string      `json:"class_dates"`
	NonTeachingDays []CalendarDay `json:"non_teaching_days"`
}

// GetCalendar returns the class dates and the non-teaching days in [from, to].
// The range may be at most as long as the longest term of the class's year.
func GetCalendar(ctx context.Context, tx pgx.Tx, classID uuid.UUID, from, to time.Time) (Calendar, error) {
	cc, err := loadClassContext(ctx, tx, classID)
	if err != nil {
		return Calendar{}, err
	}
	if to.Before(from) {
		return Calendar{}, db.NewAppError(http.StatusBadRequest, "bad_request", "to no puede ser anterior a from")
	}
	var maxDays *int
	if err := tx.QueryRow(ctx, `
		select max(ends_on - starts_on + 1) from terms
		 where academic_year_id = $1 and deleted_at is null
	`, cc.YearID).Scan(&maxDays); err != nil {
		return Calendar{}, err
	}
	if days := int(to.Sub(from).Hours()/24) + 1; maxDays == nil || days > *maxDays {
		return Calendar{}, db.NewAppError(http.StatusBadRequest, "bad_request",
			"el rango puede abarcar como máximo un periodo")
	}

	out := Calendar{}
	if out.ClassDates, err = ClassDates(ctx, tx, classID, from, to); err != nil {
		return out, err
	}
	rows, err := tx.Query(ctx, `
		select to_char(day, 'YYYY-MM-DD'), kind, label from non_teaching_days
		 where academic_year_id = $1 and deleted_at is null and day between $2 and $3
		 order by day
	`, cc.YearID, from, to)
	if err != nil {
		return out, err
	}
	defer rows.Close()
	out.NonTeachingDays = []CalendarDay{}
	for rows.Next() {
		var d CalendarDay
		if err := rows.Scan(&d.Date, &d.Kind, &d.Label); err != nil {
			return out, err
		}
		out.NonTeachingDays = append(out.NonTeachingDays, d)
	}
	return out, rows.Err()
}

// ------------------------------------------------------------ experience --

type ExperienceCompetency struct {
	ID   uuid.UUID `json:"id"`
	Code string    `json:"code"`
	Name string    `json:"name"`
}

type ExperienceCriterion struct {
	ID            uuid.UUID   `json:"id"`
	ExperienceID  uuid.UUID   `json:"experience_id"`
	CompetencyID  uuid.UUID   `json:"competency_id"`
	Description   string      `json:"description"`
	CapabilityIDs []uuid.UUID `json:"capability_ids"`
	PerformanceID *uuid.UUID  `json:"performance_id"`
	ProposedBy    string      `json:"proposed_by"`
	AcceptedAt    *string     `json:"accepted_at"`
}

type ExperienceEvidence struct {
	ID           uuid.UUID   `json:"id"`
	ExperienceID uuid.UUID   `json:"experience_id"`
	Name         string      `json:"name"`
	Kind         string      `json:"kind"`
	CriterionIDs []uuid.UUID `json:"criterion_ids"`
	SessionDate  *string     `json:"session_date"`
	ProposedBy   string      `json:"proposed_by"`
	AcceptedAt   *string     `json:"accepted_at"`
}

type ExperienceSession struct {
	Date              string     `json:"date"`
	Title             string     `json:"title"`
	Topics            *string    `json:"topics"`
	PlannedEvidenceID *uuid.UUID `json:"planned_evidence_id"`
	ProposedBy        string     `json:"proposed_by"`
	AcceptedAt        *string    `json:"accepted_at"`
}

// Warning is something the summary screen shows; it never blocks.
type Warning struct {
	Code         string     `json:"code"`
	CompetencyID *uuid.UUID `json:"competency_id,omitempty"`
	CapabilityID *uuid.UUID `json:"capability_id,omitempty"`
	Count        *int       `json:"count,omitempty"`
}

type Experience struct {
	ID            uuid.UUID              `json:"id"`
	ClassID       uuid.UUID              `json:"class_id"`
	TermID        uuid.UUID              `json:"term_id"`
	Status        string                 `json:"status"`
	Title         string                 `json:"title"`
	IdeaText      string                 `json:"idea_text"`
	SituationText *string                `json:"situation_text"`
	StartsOn      string                 `json:"starts_on"`
	EndsOn        string                 `json:"ends_on"`
	Competencies  []ExperienceCompetency `json:"competencies"`
	Criteria      []ExperienceCriterion  `json:"criteria"`
	Evidences     []ExperienceEvidence   `json:"evidences"`
	Sessions      []ExperienceSession    `json:"sessions"`
	ClassDates    []string               `json:"class_dates"`
	Warnings      []Warning              `json:"warnings"`
}

// isoUTC renders a timestamptz column as the API's UTC timestamp.
const isoUTC = `'YYYY-MM-DD"T"HH24:MI:SS"Z"'`

// GetExperience returns the whole experience for the review, criteria,
// evidences, sessions and summary screens.
func GetExperience(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID) (Experience, error) {
	var e Experience
	var from, to time.Time
	err := tx.QueryRow(ctx, `
		select id, class_id, term_id, status, title, idea_text, situation_text, starts_on, ends_on
		  from learning_experiences
		 where id = $1 and deleted_at is null
	`, experienceID).Scan(&e.ID, &e.ClassID, &e.TermID, &e.Status, &e.Title, &e.IdeaText,
		&e.SituationText, &from, &to)
	if err != nil {
		return e, err
	}
	e.StartsOn, e.EndsOn = from.Format(dateLayout), to.Format(dateLayout)

	rows, err := tx.Query(ctx, `
		select c.id, c.code, c.name
		  from experience_competencies ec
		  join competencies c on c.id = ec.competency_id
		 where ec.experience_id = $1 and ec.deleted_at is null
		 order by c.sort_order, c.code
	`, experienceID)
	if err != nil {
		return e, err
	}
	e.Competencies = []ExperienceCompetency{}
	for rows.Next() {
		var c ExperienceCompetency
		if err := rows.Scan(&c.ID, &c.Code, &c.Name); err != nil {
			rows.Close()
			return e, err
		}
		e.Competencies = append(e.Competencies, c)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return e, err
	}

	if e.Criteria, err = listExperienceCriteria(ctx, tx, experienceID, uuid.Nil); err != nil {
		return e, err
	}
	if e.Evidences, err = listExperienceEvidences(ctx, tx, experienceID, uuid.Nil); err != nil {
		return e, err
	}
	if e.Sessions, err = listExperienceSessions(ctx, tx, experienceID, nil); err != nil {
		return e, err
	}
	if e.ClassDates, err = ClassDates(ctx, tx, e.ClassID, from, to); err != nil {
		return e, err
	}
	e.Warnings, err = experienceWarnings(ctx, tx, experienceID)
	return e, err
}

// listExperienceCriteria returns the experience's criteria, or only one of
// them when criterionID is set.
func listExperienceCriteria(ctx context.Context, tx pgx.Tx, experienceID, criterionID uuid.UUID) ([]ExperienceCriterion, error) {
	rows, err := tx.Query(ctx, `
		select cr.id, cr.experience_id, cr.competency_id, cr.description,
		       coalesce((select array_agg(x.capability_id order by cap.sort_order, cap.code)
		                   from evaluation_criterion_capabilities x
		                   join capabilities cap on cap.id = x.capability_id
		                  where x.criterion_id = cr.id and x.deleted_at is null), '{}'),
		       cr.performance_id, cr.proposed_by,
		       to_char(cr.accepted_at at time zone 'UTC', `+isoUTC+`)
		  from evaluation_criteria cr
		  join competencies c on c.id = cr.competency_id
		 where cr.experience_id = $1 and cr.deleted_at is null
		   and ($2::uuid is null or cr.id = $2)
		 order by c.sort_order, c.code, cr.sort_order, cr.created_at
	`, experienceID, nullUUID(criterionID))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []ExperienceCriterion{}
	for rows.Next() {
		var c ExperienceCriterion
		if err := rows.Scan(&c.ID, &c.ExperienceID, &c.CompetencyID, &c.Description, &c.CapabilityIDs,
			&c.PerformanceID, &c.ProposedBy, &c.AcceptedAt); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// listExperienceEvidences returns the experience's planned evidences, or only
// one of them when evidenceID is set.
func listExperienceEvidences(ctx context.Context, tx pgx.Tx, experienceID, evidenceID uuid.UUID) ([]ExperienceEvidence, error) {
	rows, err := tx.Query(ctx, `
		select pe.id, pe.experience_id, pe.name, pe.kind,
		       coalesce((select array_agg(pc.criterion_id order by pc.created_at)
		                   from planned_evidence_criteria pc
		                  where pc.evidence_id = pe.id and pc.deleted_at is null), '{}'),
		       to_char(se.class_date, 'YYYY-MM-DD'), pe.proposed_by,
		       to_char(pe.accepted_at at time zone 'UTC', `+isoUTC+`)
		  from planned_evidences pe
		  left join session_outline_entries se on se.id = pe.session_entry_id and se.deleted_at is null
		 where pe.experience_id = $1 and pe.deleted_at is null
		   and ($2::uuid is null or pe.id = $2)
		 order by pe.created_at, pe.id
	`, experienceID, nullUUID(evidenceID))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []ExperienceEvidence{}
	for rows.Next() {
		var ev ExperienceEvidence
		if err := rows.Scan(&ev.ID, &ev.ExperienceID, &ev.Name, &ev.Kind, &ev.CriterionIDs, &ev.SessionDate,
			&ev.ProposedBy, &ev.AcceptedAt); err != nil {
			return nil, err
		}
		out = append(out, ev)
	}
	return out, rows.Err()
}

// listExperienceSessions returns the experience's session outline, or only
// the entry of one date when date is set.
func listExperienceSessions(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID, date *time.Time) ([]ExperienceSession, error) {
	rows, err := tx.Query(ctx, `
		select to_char(class_date, 'YYYY-MM-DD'), title, topics, planned_evidence_id, proposed_by,
		       to_char(accepted_at at time zone 'UTC', `+isoUTC+`)
		  from session_outline_entries
		 where experience_id = $1 and deleted_at is null
		   and ($2::date is null or class_date = $2)
		 order by class_date
	`, experienceID, date)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []ExperienceSession{}
	for rows.Next() {
		var s ExperienceSession
		if err := rows.Scan(&s.Date, &s.Title, &s.Topics, &s.PlannedEvidenceID, &s.ProposedBy, &s.AcceptedAt); err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

// experienceWarnings lists, for every capability of the experience's
// competencies, the ones no accepted criterion looks at, then how many
// proposals are still pending.
func experienceWarnings(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID) ([]Warning, error) {
	rows, err := tx.Query(ctx, `
		select c.id, cap.id
		  from experience_competencies ec
		  join competencies c on c.id = ec.competency_id
		  join capabilities cap on cap.competency_id = c.id and cap.is_active and cap.deleted_at is null
		 where ec.experience_id = $1 and ec.deleted_at is null
		   and not exists (
		     select 1 from evaluation_criteria cr
		       join evaluation_criterion_capabilities x on x.criterion_id = cr.id and x.deleted_at is null
		      where cr.experience_id = ec.experience_id and cr.deleted_at is null
		        and cr.accepted_at is not null and x.capability_id = cap.id
		   )
		 order by c.sort_order, c.code, cap.sort_order, cap.code
	`, experienceID)
	if err != nil {
		return nil, err
	}
	out := []Warning{}
	for rows.Next() {
		var compID, capID uuid.UUID
		if err := rows.Scan(&compID, &capID); err != nil {
			rows.Close()
			return nil, err
		}
		out = append(out, Warning{Code: "capability_without_criterion", CompetencyID: &compID, CapabilityID: &capID})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}

	var pending int
	if err := tx.QueryRow(ctx, `
		select (select count(*) from evaluation_criteria
		         where experience_id = $1 and deleted_at is null and accepted_at is null)
		     + (select count(*) from planned_evidences
		         where experience_id = $1 and deleted_at is null and accepted_at is null)
		     + (select count(*) from session_outline_entries
		         where experience_id = $1 and deleted_at is null and accepted_at is null)
	`, experienceID).Scan(&pending); err != nil {
		return nil, err
	}
	if pending > 0 {
		out = append(out, Warning{Code: "pending_proposals", Count: &pending})
	}
	return out, nil
}
