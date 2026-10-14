package repo

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/db"
	"mawta-server/internal/domain"
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

// scheduledClassDays returns the dates in [from, to] the class meets, in order:
// the days its weekly schedule covers plus the days it has a session, so a class
// with sessions but no schedule rows still gets its real days. Unlike ClassDates
// it keeps non-teaching days: the timeline shows a feriado as one of the class's
// slots.
func scheduledClassDays(ctx context.Context, tx pgx.Tx, classID uuid.UUID, from, to time.Time) ([]string, error) {
	rows, err := tx.Query(ctx, `
		select to_char(d, 'YYYY-MM-DD')
		  from generate_series($2::date, $3::date, interval '1 day') d
		 where exists (
		   select 1 from class_schedules s
		    where s.class_id = $1
		      and s.deleted_at is null
		      and s.weekday = extract(isodow from d)
		      and s.effective_from <= d
		      and (s.effective_to is null or d < s.effective_to)
		 )
		    or exists (
		   select 1 from class_sessions cs
		    where cs.class_id = $1
		      and cs.deleted_at is null
		      and cs.status <> 'cancelled'
		      and cs.session_date = d
		 )
		 order by d
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
	// EvidencesThisTerm counts the distinct evidences of the class in this term
	// that observe the competency, and EvidenceKinds their kinds. InTerm tells
	// whether an experience of this term plans the competency at all.
	EvidencesThisTerm int      `json:"evidences_this_term"`
	EvidenceKinds     []string `json:"evidence_kinds"`
	InTerm            bool     `json:"in_term"`
}

type Plan struct {
	Term            PlanTerm           `json:"term"`
	NonTeachingDays []NonTeachingRange `json:"non_teaching_days"`
	ClassDatesTotal int                `json:"class_dates_total"`
	// The days the weekly schedule meets in the term, holidays included: a
	// feriado on a class day is a class slot the timeline marks, not a missing one.
	ScheduledClassDays []string         `json:"scheduled_class_days"`
	Experiences        []PlanExperience `json:"experiences"`
	Competencies       []PlanCompetency `json:"competencies"`
}

// ResolvePlanTerm picks the term "Tu trimestre" shows: termID when given
// (it must be a term of the class's year), else the term containing today,
// else the next one, else the last one. Terms of another stage are skipped.
//
// This is not ResolveTerm: planning shows where the teacher is in the year,
// by date, whether or not the term has been activated yet.
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
	if p.ScheduledClassDays, err = scheduledClassDays(ctx, tx, classID, term.from, term.to); err != nil {
		return p, err
	}
	if p.Experiences, err = planExperiences(ctx, tx, classID, term.ID); err != nil {
		return p, err
	}
	if p.Competencies, err = planCompetencies(ctx, tx, classID, cc, term); err != nil {
		return p, err
	}
	return p, fillEvidenceTallies(ctx, tx, classID, term.ID, p.Competencies)
}

// EvidenceTally is how much evidence a competency has in a term.
type EvidenceTally struct {
	Count int
	Kinds []string
}

// termEvidenceByCompetency counts, per competency, the distinct evidences of
// the class in the term that observe it: accepted planned evidences (drafts
// included, as the plan does) and hand-added assessments. Assessments synced
// from a planned evidence are left out, so a planned evidence is counted once.
func termEvidenceByCompetency(ctx context.Context, tx pgx.Tx, classID, termID uuid.UUID) (map[uuid.UUID]EvidenceTally, error) {
	rows, err := tx.Query(ctx, `
		select u.competency_id, count(distinct u.evidence_id), array_agg(distinct u.kind order by u.kind)
		  from (
		    select pe.id as evidence_id, cr.competency_id, pe.kind
		      from planned_evidences pe
		      join learning_experiences le on le.id = pe.experience_id and le.deleted_at is null
		      join planned_evidence_criteria pec on pec.evidence_id = pe.id and pec.deleted_at is null
		      join evaluation_criteria cr on cr.id = pec.criterion_id
		       and cr.deleted_at is null and cr.accepted_at is not null
		     where le.class_id = $1 and le.term_id = $2
		       and pe.deleted_at is null and pe.accepted_at is not null
		    union all
		    select a.id, cr.competency_id, a.kind
		      from assessments a
		      join assessment_criteria ac on ac.assessment_id = a.id and ac.deleted_at is null
		      join evaluation_criteria cr on cr.id = ac.criterion_id and cr.deleted_at is null
		     where a.class_id = $1 and a.term_id = $2
		       and a.planned_evidence_id is null and a.student_id is null
		       and a.status in ('published', 'closed') and a.deleted_at is null
		  ) u
		 group by u.competency_id
	`, classID, termID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[uuid.UUID]EvidenceTally{}
	for rows.Next() {
		var id uuid.UUID
		var t EvidenceTally
		if err := rows.Scan(&id, &t.Count, &t.Kinds); err != nil {
			return nil, err
		}
		out[id] = t
	}
	return out, rows.Err()
}

// fillEvidenceTallies sets the term evidence fields of each competency in comps.
func fillEvidenceTallies(ctx context.Context, tx pgx.Tx, classID, termID uuid.UUID, comps []PlanCompetency) error {
	tally, err := termEvidenceByCompetency(ctx, tx, classID, termID)
	if err != nil {
		return err
	}
	rows, err := tx.Query(ctx, `
		select distinct ec.competency_id
		  from experience_competencies ec
		  join learning_experiences le on le.id = ec.experience_id
		 where le.class_id = $1 and le.term_id = $2
		   and le.deleted_at is null and ec.deleted_at is null
	`, classID, termID)
	if err != nil {
		return err
	}
	inTerm := map[uuid.UUID]bool{}
	for rows.Next() {
		var id uuid.UUID
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		inTerm[id] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for i := range comps {
		t := tally[comps[i].ID]
		comps[i].EvidencesThisTerm = t.Count
		comps[i].EvidenceKinds = t.Kinds
		if comps[i].EvidenceKinds == nil {
			comps[i].EvidenceKinds = []string{}
		}
		comps[i].InTerm = inTerm[comps[i].ID]
	}
	return nil
}

// Range returns the term's first and last day.
func (t PlanTerm) Range() (from, to time.Time) { return t.from, t.to }

// FreeWindow is a stretch of a term no experience of the class occupies,
// with how many class dates it holds. The planning agent picks experience
// dates inside one.
type FreeWindow struct {
	StartsOn   string `json:"starts_on"`
	EndsOn     string `json:"ends_on"`
	ClassDates int    `json:"class_dates"`
}

// FreeWindows returns the stretches of the term not covered by any
// non-deleted experience of the class (drafts included, as
// learning_experiences_no_overlap counts them), in order.
func FreeWindows(ctx context.Context, tx pgx.Tx, classID uuid.UUID, term PlanTerm) ([]FreeWindow, error) {
	rows, err := tx.Query(ctx, `
		select starts_on, ends_on from learning_experiences
		 where class_id = $1 and deleted_at is null
		   and daterange(starts_on, ends_on, '[]') && daterange($2::date, $3::date, '[]')
		 order by starts_on
	`, classID, term.from, term.to)
	if err != nil {
		return nil, err
	}
	type span struct{ from, to time.Time }
	var busy []span
	for rows.Next() {
		var b span
		if err := rows.Scan(&b.from, &b.to); err != nil {
			rows.Close()
			return nil, err
		}
		busy = append(busy, b)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}

	var gaps []span
	cursor := term.from
	for _, b := range busy {
		if b.from.After(cursor) {
			gaps = append(gaps, span{cursor, b.from.AddDate(0, 0, -1)})
		}
		if next := b.to.AddDate(0, 0, 1); next.After(cursor) {
			cursor = next
		}
	}
	if !cursor.After(term.to) {
		gaps = append(gaps, span{cursor, term.to})
	}

	out := []FreeWindow{}
	for _, g := range gaps {
		n, err := countClassDates(ctx, tx, classID, g.from, g.to)
		if err != nil {
			return nil, err
		}
		out = append(out, FreeWindow{StartsOn: g.from.Format(dateLayout), EndsOn: g.to.Format(dateLayout), ClassDates: n})
	}
	return out, nil
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
//   - planificada: a confirmed (status planificada) experience of this class in this
//     term works it;
//   - toca: otherwise, when it still needs terms to reach two worked terms in
//     the year and the terms left (this one included) are no more than it needs;
//   - puede_esperar: otherwise.
//
// A worked term is a term of the year with a confirmed experience of this
// class working the competency. A borrador is still being built, so it does
// not count as work done, and the capacities it covers are not counted either.
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
		     and le.status = 'planificada'
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
		     and le.status = 'planificada'
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

// CurriculumStandard is the learning standard a competency reaches at the end
// of the class's cycle, verbatim from the CNEB.
type CurriculumStandard struct {
	Level int16  `json:"level"`
	Text  string `json:"text"`
}

type CurriculumCompetency struct {
	ID           uuid.UUID               `json:"id"`
	Code         string                  `json:"code"`
	Name         string                  `json:"name"`
	Kind         string                  `json:"kind"`
	Standard     *CurriculumStandard     `json:"standard"`
	Capabilities []CurriculumCapability  `json:"capabilities"`
	Performances []CurriculumPerformance `json:"performances"`
}

type Curriculum struct {
	Grade        CurriculumGrade        `json:"grade"`
	Competencies []CurriculumCompetency `json:"competencies"`
}

// GetCurriculum returns the competencies of the class's área with their
// capabilities, the standard of the class's cycle and the performances of the
// class's grade. The standard is the main source of criteria; performances are
// optional support.
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

	if out.Grade.ExpectedLevel != nil {
		rows, err = tx.Query(ctx, `
			select s.competency_id, s.level, s.official_text
			  from learning_standards s
			  join competencies c on c.id = s.competency_id
			 where c.subject_id = $1 and s.level = $2 and s.deleted_at is null
		`, cc.SubjectID, *out.Grade.ExpectedLevel)
		if err != nil {
			return out, err
		}
		for rows.Next() {
			var compID uuid.UUID
			var st CurriculumStandard
			if err := rows.Scan(&compID, &st.Level, &st.Text); err != nil {
				rows.Close()
				return out, err
			}
			if i, ok := index[compID]; ok {
				out.Competencies[i].Standard = &st
			}
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return out, err
		}
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
	ID           uuid.UUID `json:"id"`
	ExperienceID uuid.UUID `json:"experience_id"`
	Name         string    `json:"name"`
	Kind         string    `json:"kind"`
	// ValueScale is how the evidence will be valued once the experience is
	// planned: 'numeric' (a mark out of MaxScore) or 'ordinal' (AD/A/B/C).
	ValueScale   string      `json:"value_scale"`
	MaxScore     *float64    `json:"max_score"`
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
	Kind         *string    `json:"kind,omitempty"`
}

type Experience struct {
	ID            uuid.UUID              `json:"id"`
	ClassID       uuid.UUID              `json:"class_id"`
	TermID        uuid.UUID              `json:"term_id"`
	Status        string                 `json:"status"`
	Title         string                 `json:"title"`
	IdeaText      string                 `json:"idea_text"`
	SituationText *string                `json:"situation_text"`
	ContextText   *string                `json:"context_text"`
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
		select id, class_id, term_id, status, title, idea_text, situation_text, context_text, starts_on, ends_on
		  from learning_experiences
		 where id = $1 and deleted_at is null
	`, experienceID).Scan(&e.ID, &e.ClassID, &e.TermID, &e.Status, &e.Title, &e.IdeaText,
		&e.SituationText, &e.ContextText, &from, &to)
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
		select pe.id, pe.experience_id, pe.name, pe.kind, pe.value_scale, pe.max_score,
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
		if err := rows.Scan(&ev.ID, &ev.ExperienceID, &ev.Name, &ev.Kind, &ev.ValueScale, &ev.MaxScore, &ev.CriterionIDs, &ev.SessionDate,
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

	// Evidence per competency is read over the whole term, not this experience:
	// the conclusion counts it that way, so a single experience is not an alarm.
	var classID, termID uuid.UUID
	if err := tx.QueryRow(ctx, `select class_id, term_id from learning_experiences where id = $1`,
		experienceID).Scan(&classID, &termID); err != nil {
		return nil, err
	}
	tally, err := termEvidenceByCompetency(ctx, tx, classID, termID)
	if err != nil {
		return nil, err
	}
	compRows, err := tx.Query(ctx, `
		select ec.competency_id
		  from experience_competencies ec
		  join competencies c on c.id = ec.competency_id
		 where ec.experience_id = $1 and ec.deleted_at is null
		 order by c.sort_order, c.code
	`, experienceID)
	if err != nil {
		return nil, err
	}
	var compIDs []uuid.UUID
	for compRows.Next() {
		var id uuid.UUID
		if err := compRows.Scan(&id); err != nil {
			compRows.Close()
			return nil, err
		}
		compIDs = append(compIDs, id)
	}
	compRows.Close()
	if err := compRows.Err(); err != nil {
		return nil, err
	}
	for _, id := range compIDs {
		t := tally[id]
		if t.Count < MinConclusionEvidences {
			n := t.Count
			out = append(out, Warning{Code: "competency_few_evidences", CompetencyID: &id, Count: &n})
		} else if len(t.Kinds) == 1 {
			kind := t.Kinds[0]
			out = append(out, Warning{Code: "competency_single_kind", CompetencyID: &id, Kind: &kind})
		}
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

// ---------------------------------------------------------------- writes --
//
// Every domain rule the schema enforces at commit (the deferred triggers of
// 00002) or with a raw Postgres error is checked here first, so the API
// answers with the contract's stable codes instead. The constraints stay the
// last word; db.MapError translates the two that only concurrency can reach
// (experience overlap, one session entry per date).

func badInput(code, message string) error {
	return db.NewAppError(http.StatusBadRequest, code, message)
}

func unprocessable(code, message string) error {
	return db.NewAppError(http.StatusUnprocessableEntity, code, message)
}

func conflict(code, message string) error {
	return db.NewAppError(http.StatusConflict, code, message)
}

// dedupe drops repeated ids, keeping the first occurrence's order.
func dedupe(ids []uuid.UUID) []uuid.UUID {
	seen := make(map[uuid.UUID]bool, len(ids))
	out := make([]uuid.UUID, 0, len(ids))
	for _, id := range ids {
		if !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	return out
}

// trimmedOrNil turns blank optional text into NULL.
func trimmedOrNil(s *string) *string {
	if s == nil {
		return nil
	}
	t := strings.TrimSpace(*s)
	if t == "" {
		return nil
	}
	return &t
}

type experienceHeader struct {
	ID       uuid.UUID
	ClassID  uuid.UUID
	TermID   uuid.UUID
	Status   string
	StartsOn time.Time
	EndsOn   time.Time
}

// lockExperience reads an experience and locks its row, so two edits of the
// same experience apply one after the other.
func lockExperience(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID) (experienceHeader, error) {
	var h experienceHeader
	err := tx.QueryRow(ctx, `
		select id, class_id, term_id, status, starts_on, ends_on
		  from learning_experiences
		 where id = $1 and deleted_at is null
		   for update
	`, experienceID).Scan(&h.ID, &h.ClassID, &h.TermID, &h.Status, &h.StartsOn, &h.EndsOn)
	if err == pgx.ErrNoRows {
		return h, db.NewAppError(http.StatusNotFound, "not_found", "no se encontró la experiencia")
	}
	return h, err
}

func termRange(ctx context.Context, tx pgx.Tx, termID uuid.UUID) (yearID uuid.UUID, from, to time.Time, err error) {
	err = tx.QueryRow(ctx, `
		select academic_year_id, starts_on, ends_on from terms where id = $1 and deleted_at is null
	`, termID).Scan(&yearID, &from, &to)
	if err == pgx.ErrNoRows {
		err = db.NewAppError(http.StatusNotFound, "not_found", "no se encontró el periodo")
	}
	return yearID, from, to, err
}

// checkExperienceDates applies the date rules of an experience: a valid
// range, inside its term (check_inside_term), and not crossing another
// experience of the class, drafts included (learning_experiences_no_overlap).
func checkExperienceDates(ctx context.Context, tx pgx.Tx, classID, experienceID uuid.UUID,
	termFrom, termTo, startsOn, endsOn time.Time) error {
	if endsOn.Before(startsOn) {
		return badInput("bad_request", "ends_on no puede ser anterior a starts_on")
	}
	if startsOn.Before(termFrom) || endsOn.After(termTo) {
		return unprocessable("outside_term", fmt.Sprintf(
			"la experiencia debe empezar y terminar dentro del periodo (%s a %s)",
			termFrom.Format(dateLayout), termTo.Format(dateLayout)))
	}
	var overlap bool
	if err := tx.QueryRow(ctx, `
		select exists (
		  select 1 from learning_experiences
		   where class_id = $1 and id <> $2 and deleted_at is null
		     and daterange(starts_on, ends_on, '[]') && daterange($3::date, $4::date, '[]')
		)
	`, classID, experienceID, startsOn, endsOn).Scan(&overlap); err != nil {
		return err
	}
	if overlap {
		return conflict("experience_overlap", "las fechas se cruzan con otra experiencia de esta clase")
	}
	return nil
}

// checkCompetenciesInSubject requires every competency to be an active
// competency of the class's área (check_competency_subject).
func checkCompetenciesInSubject(ctx context.Context, tx pgx.Tx, subjectID uuid.UUID, ids []uuid.UUID) error {
	var n int
	if err := tx.QueryRow(ctx, `
		select count(*) from competencies
		 where id = any($1) and subject_id = $2 and is_active and deleted_at is null
	`, ids, subjectID).Scan(&n); err != nil {
		return err
	}
	if n != len(ids) {
		return unprocessable("competency_not_in_subject", "esa competencia no es del área de esta clase")
	}
	return nil
}

type ExperienceInput struct {
	TermID        uuid.UUID
	Title         string
	IdeaText      string
	SituationText *string
	// ContextText is the event or context the teacher wrote; nil means none.
	ContextText   *string
	StartsOn      time.Time
	EndsOn        time.Time
	CompetencyIDs []uuid.UUID
}

// CreateExperience creates a draft experience with its competencies. Its
// academic year is the term's.
func CreateExperience(ctx context.Context, tx pgx.Tx, classID uuid.UUID, in ExperienceInput) (uuid.UUID, error) {
	title := strings.TrimSpace(in.Title)
	if title == "" {
		return uuid.Nil, badInput("missing_title", "la experiencia necesita un título")
	}
	idea := strings.TrimSpace(in.IdeaText)
	if idea == "" {
		return uuid.Nil, badInput("missing_idea", "la experiencia necesita la idea de la que nace")
	}
	competencyIDs := dedupe(in.CompetencyIDs)
	if len(competencyIDs) == 0 {
		return uuid.Nil, badInput("missing_competencies", "elige al menos una competencia")
	}

	cc, err := loadClassContext(ctx, tx, classID)
	if err != nil {
		return uuid.Nil, err
	}
	yearID, termFrom, termTo, err := termRange(ctx, tx, in.TermID)
	if err != nil {
		return uuid.Nil, err
	}
	if yearID != cc.YearID {
		return uuid.Nil, db.NewAppError(http.StatusNotFound, "not_found", "no se encontró el periodo")
	}
	if err := checkExperienceDates(ctx, tx, classID, uuid.Nil, termFrom, termTo, in.StartsOn, in.EndsOn); err != nil {
		return uuid.Nil, err
	}
	if err := checkCompetenciesInSubject(ctx, tx, cc.SubjectID, competencyIDs); err != nil {
		return uuid.Nil, err
	}

	var id uuid.UUID
	if err := tx.QueryRow(ctx, `
		insert into learning_experiences
		  (tenant_id, class_id, academic_year_id, term_id, title, idea_text, situation_text, context_text, starts_on, ends_on)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7, $8, $9)
		returning id
	`, classID, yearID, in.TermID, title, idea, trimmedOrNil(in.SituationText), trimmedOrNil(in.ContextText), in.StartsOn, in.EndsOn).Scan(&id); err != nil {
		return uuid.Nil, err
	}
	if _, err := tx.Exec(ctx, `
		insert into experience_competencies (tenant_id, experience_id, competency_id)
		select app.current_tenant_id(), $1, c from unnest($2::uuid[]) as c
	`, id, competencyIDs); err != nil {
		return uuid.Nil, err
	}
	return id, nil
}

// ExperiencePatch changes the fields that are set. An empty SituationText
// clears the situation. CompetencyIDs, when set, is the experience's whole
// new competency list.
type ExperiencePatch struct {
	Title         *string
	SituationText *string
	StartsOn      *time.Time
	EndsOn        *time.Time
	CompetencyIDs *[]uuid.UUID
}

// UpdateExperience edits an experience. New dates must keep its session
// outline inside them; removing a competency that still has criteria is
// refused, so no criterion is ever left on a competency the experience no
// longer works.
func UpdateExperience(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID, p ExperiencePatch) error {
	h, err := lockExperience(ctx, tx, experienceID)
	if err != nil {
		return err
	}
	if p.Title != nil && strings.TrimSpace(*p.Title) == "" {
		return badInput("missing_title", "la experiencia necesita un título")
	}

	startsOn, endsOn := h.StartsOn, h.EndsOn
	if p.StartsOn != nil {
		startsOn = *p.StartsOn
	}
	if p.EndsOn != nil {
		endsOn = *p.EndsOn
	}
	if !startsOn.Equal(h.StartsOn) || !endsOn.Equal(h.EndsOn) {
		_, termFrom, termTo, err := termRange(ctx, tx, h.TermID)
		if err != nil {
			return err
		}
		if err := checkExperienceDates(ctx, tx, h.ClassID, h.ID, termFrom, termTo, startsOn, endsOn); err != nil {
			return err
		}
		var outside bool
		if err := tx.QueryRow(ctx, `
			select exists (
			  select 1 from session_outline_entries
			   where experience_id = $1 and deleted_at is null
			     and class_date not between $2 and $3
			)
		`, h.ID, startsOn, endsOn).Scan(&outside); err != nil {
			return err
		}
		if outside {
			return unprocessable("date_not_in_experience",
				"hay sesiones planificadas fuera de las nuevas fechas; muévelas o elimínalas primero")
		}
	}

	if p.CompetencyIDs != nil {
		if err := replaceExperienceCompetencies(ctx, tx, h, dedupe(*p.CompetencyIDs)); err != nil {
			return err
		}
	}

	var title *string
	if p.Title != nil {
		t := strings.TrimSpace(*p.Title)
		title = &t
	}
	_, err = tx.Exec(ctx, `
		update learning_experiences
		   set title = coalesce($2, title),
		       situation_text = case when $3 then $4 else situation_text end,
		       starts_on = $5, ends_on = $6
		 where id = $1
	`, h.ID, title, p.SituationText != nil, trimmedOrNil(p.SituationText), startsOn, endsOn)
	return err
}

func replaceExperienceCompetencies(ctx context.Context, tx pgx.Tx, h experienceHeader, ids []uuid.UUID) error {
	if len(ids) == 0 {
		return badInput("missing_competencies", "elige al menos una competencia")
	}
	cc, err := loadClassContext(ctx, tx, h.ClassID)
	if err != nil {
		return err
	}
	if err := checkCompetenciesInSubject(ctx, tx, cc.SubjectID, ids); err != nil {
		return err
	}
	var withCriteria bool
	if err := tx.QueryRow(ctx, `
		select exists (
		  select 1 from evaluation_criteria
		   where experience_id = $1 and deleted_at is null and not (competency_id = any($2))
		)
	`, h.ID, ids).Scan(&withCriteria); err != nil {
		return err
	}
	if withCriteria {
		return conflict("competency_has_criteria",
			"esa competencia todavía tiene criterios en esta experiencia; elimínalos primero")
	}
	if _, err := tx.Exec(ctx, `
		update experience_competencies set deleted_at = now()
		 where experience_id = $1 and deleted_at is null and not (competency_id = any($2))
	`, h.ID, ids); err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `
		insert into experience_competencies (tenant_id, experience_id, competency_id)
		select app.current_tenant_id(), $1, c from unnest($2::uuid[]) as c
		 where not exists (
		   select 1 from experience_competencies ec
		    where ec.experience_id = $1 and ec.competency_id = c and ec.deleted_at is null
		 )
	`, h.ID, ids)
	return err
}

// ConfirmExperience is "Revisar y guardar": a draft becomes planned.
func ConfirmExperience(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID) error {
	h, err := lockExperience(ctx, tx, experienceID)
	if err != nil {
		return err
	}
	if h.Status != "borrador" {
		return conflict("experience_not_draft", "la experiencia ya está planificada")
	}
	if _, err = tx.Exec(ctx, `update learning_experiences set status = 'planificada' where id = $1`, h.ID); err != nil {
		return err
	}
	return SyncExperience(ctx, tx, h.ID)
}

// DeleteExperience soft-deletes an experience with everything planned in it.
// The competency links go before the experience: check_competency_subject
// reads the live experience on every write to experience_competencies.
func DeleteExperience(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID) error {
	h, err := lockExperience(ctx, tx, experienceID)
	if err != nil {
		return err
	}
	for _, q := range []string{
		`update assessments set deleted_at = now()
		  where deleted_at is null
		    and planned_evidence_id in (select id from planned_evidences where experience_id = $1)`,
		`update class_sessions cs set topic = null
		   from session_outline_entries e
		  where e.experience_id = $1 and e.deleted_at is null
		    and cs.class_id = $2 and cs.session_date = e.class_date and cs.topic = e.title`,
		`update planned_evidence_criteria set deleted_at = now()
		  where deleted_at is null
		    and evidence_id in (select id from planned_evidences where experience_id = $1)`,
		`update evaluation_criterion_capabilities set deleted_at = now()
		  where deleted_at is null
		    and criterion_id in (select id from evaluation_criteria where experience_id = $1)`,
		`update evaluation_criteria set deleted_at = now() where experience_id = $1 and deleted_at is null`,
		`update planned_evidences set deleted_at = now() where experience_id = $1 and deleted_at is null`,
		`update session_outline_entries set deleted_at = now() where experience_id = $1 and deleted_at is null`,
		`update experience_competencies set deleted_at = now() where experience_id = $1 and deleted_at is null`,
		`update learning_experiences set deleted_at = now() where id = $1`,
	} {
		args := []any{h.ID}
		if strings.Contains(q, "$2") {
			args = append(args, h.ClassID)
		}
		if _, err := tx.Exec(ctx, q, args...); err != nil {
			return err
		}
	}
	return nil
}

// -------------------------------------------------------------- criteria --

type CriterionInput struct {
	CompetencyID  uuid.UUID
	Description   string
	CapabilityIDs []uuid.UUID
	// PerformanceID is optional: the standard is the main source of a criterion.
	PerformanceID *uuid.UUID
}

// checkCriterionCompetency requires the competency to be one the experience
// works (check_criterion_experience).
func checkCriterionCompetency(ctx context.Context, tx pgx.Tx, h experienceHeader, competencyID uuid.UUID) error {
	var inExperience bool
	if err := tx.QueryRow(ctx, `
		select exists (
		  select 1 from experience_competencies
		   where experience_id = $1 and competency_id = $2 and deleted_at is null
		)
	`, h.ID, competencyID).Scan(&inExperience); err != nil {
		return err
	}
	if inExperience {
		return nil
	}
	cc, err := loadClassContext(ctx, tx, h.ClassID)
	if err != nil {
		return err
	}
	if err := checkCompetenciesInSubject(ctx, tx, cc.SubjectID, []uuid.UUID{competencyID}); err != nil {
		return err
	}
	return unprocessable("competency_not_in_experience",
		"esa competencia no está en esta experiencia; agrégala a la experiencia primero")
}

// checkCriterionCapabilities requires at least one capability, all of the
// criterion's competency (check_criterion_has_capability and the composite
// FK of evaluation_criterion_capabilities).
func checkCriterionCapabilities(ctx context.Context, tx pgx.Tx, competencyID uuid.UUID, ids []uuid.UUID) error {
	if len(ids) == 0 {
		return unprocessable("criterion_needs_capability", "un criterio mira al menos una capacidad")
	}
	var n int
	if err := tx.QueryRow(ctx, `
		select count(*) from capabilities
		 where id = any($1) and competency_id = $2 and is_active and deleted_at is null
	`, ids, competencyID).Scan(&n); err != nil {
		return err
	}
	if n != len(ids) {
		return unprocessable("capability_not_in_competency", "esa capacidad no es de la competencia del criterio")
	}
	return nil
}

// checkCriterionPerformance requires the performance to be one of the
// competency's for the class's grade.
func checkCriterionPerformance(ctx context.Context, tx pgx.Tx, classID, competencyID, performanceID uuid.UUID) error {
	var ok bool
	if err := tx.QueryRow(ctx, `
		select exists (
		  select 1
		    from grade_level_performances p
		    join courses co on co.grade_level_id = p.grade_level_id
		    join classes cl on cl.course_id = co.id
		   where cl.id = $1 and p.competency_id = $2 and p.id = $3 and p.deleted_at is null
		)
	`, classID, competencyID, performanceID).Scan(&ok); err != nil {
		return err
	}
	if !ok {
		return unprocessable("performance_not_in_grade", "ese desempeño no es de esta competencia en el grado de la clase")
	}
	return nil
}

// Who wrote a planning row (proposed_by). A teacher's row is accepted when
// written; Mawta's stays pending (accepted_at null) until the teacher accepts
// or edits it.
const (
	byTeacher = "teacher"
	byMawta   = "mawta"
)

// CreatePlannedCriterion writes a teacher's criterion for one of the
// experience's competencies, with its capabilities, in the same transaction:
// check_criterion_on_write fails the commit for a criterion without them.
func CreatePlannedCriterion(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID, in CriterionInput) (uuid.UUID, error) {
	return createPlannedCriterion(ctx, tx, experienceID, in, byTeacher)
}

// ProposeCriterion writes a criterion the planning agent proposes. It passes
// the same checks as a teacher's and stays pending until the teacher accepts
// or edits it.
func ProposeCriterion(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID, in CriterionInput) (uuid.UUID, error) {
	return createPlannedCriterion(ctx, tx, experienceID, in, byMawta)
}

func createPlannedCriterion(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID, in CriterionInput, by string) (uuid.UUID, error) {
	h, err := lockExperience(ctx, tx, experienceID)
	if err != nil {
		return uuid.Nil, err
	}
	description := strings.TrimSpace(in.Description)
	if description == "" {
		return uuid.Nil, badInput("missing_description",
			"un criterio necesita una descripción: es contra lo que se lee la evidencia")
	}
	capabilityIDs := dedupe(in.CapabilityIDs)
	if err := checkCriterionCompetency(ctx, tx, h, in.CompetencyID); err != nil {
		return uuid.Nil, err
	}
	if err := checkCriterionCapabilities(ctx, tx, in.CompetencyID, capabilityIDs); err != nil {
		return uuid.Nil, err
	}
	if in.PerformanceID != nil {
		if err := checkCriterionPerformance(ctx, tx, h.ClassID, in.CompetencyID, *in.PerformanceID); err != nil {
			return uuid.Nil, err
		}
	}

	var id uuid.UUID
	if err := tx.QueryRow(ctx, `
		insert into evaluation_criteria
		  (tenant_id, competency_id, description, sort_order, experience_id, performance_id,
		   proposed_by, accepted_at)
		select app.current_tenant_id(), $1, $2, coalesce(max(sort_order), 0) + 1, $3, $4,
		       $5, case when $5 = 'teacher' then now() end
		  from evaluation_criteria where experience_id = $3 and deleted_at is null
		returning id
	`, in.CompetencyID, description, h.ID, in.PerformanceID, by).Scan(&id); err != nil {
		return uuid.Nil, err
	}
	return id, setCriterionCapabilities(ctx, tx, id, in.CompetencyID, capabilityIDs)
}

// setCriterionCapabilities makes ids the criterion's whole capability list.
// competency_id is copied from the criterion, as
// check_criterion_capability_competency requires.
func setCriterionCapabilities(ctx context.Context, tx pgx.Tx, criterionID, competencyID uuid.UUID, ids []uuid.UUID) error {
	if _, err := tx.Exec(ctx, `
		update evaluation_criterion_capabilities set deleted_at = now()
		 where criterion_id = $1 and deleted_at is null and not (capability_id = any($2))
	`, criterionID, ids); err != nil {
		return err
	}
	_, err := tx.Exec(ctx, `
		insert into evaluation_criterion_capabilities (tenant_id, criterion_id, competency_id, capability_id)
		select app.current_tenant_id(), $1, $2, c from unnest($3::uuid[]) as c
		 where not exists (
		   select 1 from evaluation_criterion_capabilities x
		    where x.criterion_id = $1 and x.capability_id = c and x.deleted_at is null
		 )
	`, criterionID, competencyID, ids)
	return err
}

// CriterionPatch changes the fields that are set. PerformanceIDSet with a nil
// PerformanceID removes the criterion's performance.
type CriterionPatch struct {
	Description      *string
	CapabilityIDs    *[]uuid.UUID
	PerformanceID    *uuid.UUID
	PerformanceIDSet bool
}

// lockPlannedCriterion reads a criterion of an experience and locks its
// experience. A global criterion is not part of any plan: not found.
func lockPlannedCriterion(ctx context.Context, tx pgx.Tx, criterionID uuid.UUID) (experienceHeader, uuid.UUID, error) {
	var experienceID, competencyID uuid.UUID
	err := tx.QueryRow(ctx, `
		select experience_id, competency_id from evaluation_criteria
		 where id = $1 and experience_id is not null and deleted_at is null
	`, criterionID).Scan(&experienceID, &competencyID)
	if err == pgx.ErrNoRows {
		return experienceHeader{}, uuid.Nil, db.NewAppError(http.StatusNotFound, "not_found", "no se encontró el criterio")
	}
	if err != nil {
		return experienceHeader{}, uuid.Nil, err
	}
	h, err := lockExperience(ctx, tx, experienceID)
	return h, competencyID, err
}

// UpdatePlannedCriterion edits a criterion. Editing a proposal accepts it.
func UpdatePlannedCriterion(ctx context.Context, tx pgx.Tx, criterionID uuid.UUID, p CriterionPatch) error {
	h, competencyID, err := lockPlannedCriterion(ctx, tx, criterionID)
	if err != nil {
		return err
	}
	var description *string
	if p.Description != nil {
		d := strings.TrimSpace(*p.Description)
		if d == "" {
			return badInput("missing_description",
				"un criterio necesita una descripción: es contra lo que se lee la evidencia")
		}
		description = &d
	}
	if p.PerformanceIDSet && p.PerformanceID != nil {
		if err := checkCriterionPerformance(ctx, tx, h.ClassID, competencyID, *p.PerformanceID); err != nil {
			return err
		}
	}
	if p.CapabilityIDs != nil {
		ids := dedupe(*p.CapabilityIDs)
		if err := checkCriterionCapabilities(ctx, tx, competencyID, ids); err != nil {
			return err
		}
		if err := setCriterionCapabilities(ctx, tx, criterionID, competencyID, ids); err != nil {
			return err
		}
	}
	_, err = tx.Exec(ctx, `
		update evaluation_criteria
		   set description = coalesce($2, description),
		       performance_id = case when $4 then $3 else performance_id end,
		       accepted_at = coalesce(accepted_at, now())
		 where id = $1
	`, criterionID, description, p.PerformanceID, p.PerformanceIDSet)
	return err
}

// AcceptPlannedCriterion accepts a proposal unchanged. Accepting an accepted
// criterion is a no-op.
func AcceptPlannedCriterion(ctx context.Context, tx pgx.Tx, criterionID uuid.UUID) error {
	if _, _, err := lockPlannedCriterion(ctx, tx, criterionID); err != nil {
		return err
	}
	_, err := tx.Exec(ctx, `
		update evaluation_criteria set accepted_at = coalesce(accepted_at, now()) where id = $1
	`, criterionID)
	return err
}

// GetPlannedCriterion returns one criterion of an experience.
func GetPlannedCriterion(ctx context.Context, tx pgx.Tx, criterionID uuid.UUID) (ExperienceCriterion, error) {
	var experienceID uuid.UUID
	if err := tx.QueryRow(ctx, `
		select experience_id from evaluation_criteria
		 where id = $1 and experience_id is not null and deleted_at is null
	`, criterionID).Scan(&experienceID); err != nil {
		return ExperienceCriterion{}, err
	}
	list, err := listExperienceCriteria(ctx, tx, experienceID, criterionID)
	if err != nil {
		return ExperienceCriterion{}, err
	}
	if len(list) == 0 {
		return ExperienceCriterion{}, pgx.ErrNoRows
	}
	return list[0], nil
}

// ------------------------------------------------------------- evidences --

type EvidenceInput struct {
	Name string
	Kind string
	// ValueScale is 'numeric' or 'ordinal'; empty means numeric. MaxScore is
	// the numeric maximum; nil means the default of defaultEvidenceMaxScore.
	ValueScale   string
	MaxScore     *float64
	CriterionIDs []uuid.UUID
	SessionDate  *time.Time
}

// defaultEvidenceMaxScore is the maximum a numeric planned evidence gets when
// the teacher names none. It is only a default: any positive maximum is valid.
const defaultEvidenceMaxScore = 20

// resolveEvidenceScale validates a scale and its maximum and fills in the
// default. A numeric evidence always ends with a maximum; an ordinal one never
// has one.
func resolveEvidenceScale(valueScale string, maxScore *float64) (string, *float64, error) {
	if valueScale == "" {
		valueScale = "numeric"
	}
	switch valueScale {
	case "numeric":
		if maxScore == nil {
			m := float64(defaultEvidenceMaxScore)
			return valueScale, &m, nil
		}
		if *maxScore <= 0 {
			return "", nil, badInput("bad_request", "max_score debe ser mayor que 0")
		}
		return valueScale, maxScore, nil
	case "ordinal":
		if maxScore != nil {
			return "", nil, badInput("bad_request", "una evidencia ordinal (AD/A/B/C) no lleva max_score")
		}
		return valueScale, nil, nil
	}
	return "", nil, badInput("bad_request", "value_scale debe ser numeric u ordinal")
}

func checkEvidenceKind(kind string) error {
	if !domain.IsEvidenceKind(kind) {
		return badInput("bad_request", "kind debe ser produccion o actuacion")
	}
	return nil
}

// checkEvidenceCriteria requires at least one criterion, all of this
// experience (check_evidence_criterion_experience). They may come from any
// of its competencies.
func checkEvidenceCriteria(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID, ids []uuid.UUID) error {
	if len(ids) == 0 {
		return badInput("missing_criteria", "una evidencia observa al menos un criterio")
	}
	var n int
	if err := tx.QueryRow(ctx, `
		select count(*) from evaluation_criteria
		 where id = any($1) and experience_id = $2 and deleted_at is null
	`, ids, experienceID).Scan(&n); err != nil {
		return err
	}
	if n != len(ids) {
		return unprocessable("criterion_other_experience", "ese criterio no es de esta experiencia")
	}
	return nil
}

// sessionEntryAt returns the experience's session entry of a date, which a
// placed evidence needs.
func sessionEntryAt(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID, date time.Time) (uuid.UUID, error) {
	var id uuid.UUID
	err := tx.QueryRow(ctx, `
		select id from session_outline_entries
		 where experience_id = $1 and class_date = $2 and deleted_at is null
	`, experienceID, date).Scan(&id)
	if err == pgx.ErrNoRows {
		return uuid.Nil, unprocessable("date_not_in_experience",
			"no hay una sesión planificada en esa fecha de la experiencia")
	}
	return id, err
}

// placeEvidence sets where an evidence is collected, keeping both sides of
// the relation in step: planned_evidences.session_entry_id and
// session_outline_entries.planned_evidence_id. A session holds one evidence,
// so placing an evidence in a session unplaces the one that was there.
func placeEvidence(ctx context.Context, tx pgx.Tx, evidenceID uuid.UUID, entryID *uuid.UUID) error {
	if _, err := tx.Exec(ctx, `
		update session_outline_entries set planned_evidence_id = null
		 where planned_evidence_id = $1 and deleted_at is null and ($2::uuid is null or id <> $2)
	`, evidenceID, entryID); err != nil {
		return err
	}
	if entryID != nil {
		if _, err := tx.Exec(ctx, `
			update planned_evidences set session_entry_id = null
			 where session_entry_id = $1 and id <> $2
		`, *entryID, evidenceID); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
			update session_outline_entries set planned_evidence_id = $2 where id = $1
		`, *entryID, evidenceID); err != nil {
			return err
		}
	}
	_, err := tx.Exec(ctx, `update planned_evidences set session_entry_id = $2 where id = $1`, evidenceID, entryID)
	return err
}

// unplaceEntry empties a session entry and unplaces the evidence it held.
func unplaceEntry(ctx context.Context, tx pgx.Tx, entryID uuid.UUID) error {
	if _, err := tx.Exec(ctx, `
		update planned_evidences set session_entry_id = null where session_entry_id = $1
	`, entryID); err != nil {
		return err
	}
	_, err := tx.Exec(ctx, `
		update session_outline_entries set planned_evidence_id = null
		 where id = $1 and planned_evidence_id is not null
	`, entryID)
	return err
}

func setEvidenceCriteria(ctx context.Context, tx pgx.Tx, evidenceID uuid.UUID, ids []uuid.UUID) error {
	if _, err := tx.Exec(ctx, `
		update planned_evidence_criteria set deleted_at = now()
		 where evidence_id = $1 and deleted_at is null and not (criterion_id = any($2))
	`, evidenceID, ids); err != nil {
		return err
	}
	_, err := tx.Exec(ctx, `
		insert into planned_evidence_criteria (tenant_id, evidence_id, criterion_id)
		select app.current_tenant_id(), $1, c from unnest($2::uuid[]) as c
		 where not exists (
		   select 1 from planned_evidence_criteria pc
		    where pc.evidence_id = $1 and pc.criterion_id = c and pc.deleted_at is null
		 )
	`, evidenceID, ids)
	return err
}

// CreatePlannedEvidence writes a teacher's planned evidence, optionally
// placed in the session entry of SessionDate.
func CreatePlannedEvidence(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID, in EvidenceInput) (uuid.UUID, error) {
	id, err := createPlannedEvidence(ctx, tx, experienceID, in, byTeacher)
	if err != nil {
		return uuid.Nil, err
	}
	return id, SyncExperience(ctx, tx, experienceID)
}

// ProposeEvidence writes a planned evidence the planning agent proposes,
// pending until the teacher accepts or edits it.
func ProposeEvidence(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID, in EvidenceInput) (uuid.UUID, error) {
	return createPlannedEvidence(ctx, tx, experienceID, in, byMawta)
}

func createPlannedEvidence(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID, in EvidenceInput, by string) (uuid.UUID, error) {
	h, err := lockExperience(ctx, tx, experienceID)
	if err != nil {
		return uuid.Nil, err
	}
	name := strings.TrimSpace(in.Name)
	if name == "" {
		return uuid.Nil, badInput("missing_name", "la evidencia necesita un nombre")
	}
	if err := checkEvidenceKind(in.Kind); err != nil {
		return uuid.Nil, err
	}
	valueScale, maxScore, err := resolveEvidenceScale(in.ValueScale, in.MaxScore)
	if err != nil {
		return uuid.Nil, err
	}
	criterionIDs := dedupe(in.CriterionIDs)
	if err := checkEvidenceCriteria(ctx, tx, h.ID, criterionIDs); err != nil {
		return uuid.Nil, err
	}
	var entryID *uuid.UUID
	if in.SessionDate != nil {
		id, err := sessionEntryAt(ctx, tx, h.ID, *in.SessionDate)
		if err != nil {
			return uuid.Nil, err
		}
		entryID = &id
	}

	var id uuid.UUID
	if err := tx.QueryRow(ctx, `
		insert into planned_evidences (tenant_id, experience_id, name, kind, value_scale, max_score,
		                               proposed_by, accepted_at)
		values (app.current_tenant_id(), $1, $2, $3, $5, $6, $4, case when $4 = 'teacher' then now() end)
		returning id
	`, h.ID, name, in.Kind, by, valueScale, maxScore).Scan(&id); err != nil {
		return uuid.Nil, err
	}
	if err := setEvidenceCriteria(ctx, tx, id, criterionIDs); err != nil {
		return uuid.Nil, err
	}
	if entryID != nil {
		if err := placeEvidence(ctx, tx, id, entryID); err != nil {
			return uuid.Nil, err
		}
	}
	return id, nil
}

// EvidencePatch changes the fields that are set. SessionDateSet with a nil
// SessionDate unplaces the evidence.
type EvidencePatch struct {
	Name *string
	Kind *string
	// ValueScale and MaxScore change how the evidence will be valued. Setting
	// the scale to ordinal clears the maximum; setting only MaxScore keeps a
	// numeric scale.
	ValueScale     *string
	MaxScore       *float64
	CriterionIDs   *[]uuid.UUID
	SessionDateSet bool
	SessionDate    *time.Time
}

func lockPlannedEvidence(ctx context.Context, tx pgx.Tx, evidenceID uuid.UUID) (experienceHeader, error) {
	var experienceID uuid.UUID
	err := tx.QueryRow(ctx, `
		select experience_id from planned_evidences where id = $1 and deleted_at is null
	`, evidenceID).Scan(&experienceID)
	if err == pgx.ErrNoRows {
		return experienceHeader{}, db.NewAppError(http.StatusNotFound, "not_found", "no se encontró la evidencia")
	}
	if err != nil {
		return experienceHeader{}, err
	}
	return lockExperience(ctx, tx, experienceID)
}

// UpdatePlannedEvidence edits a planned evidence. Editing a proposal accepts
// it.
func UpdatePlannedEvidence(ctx context.Context, tx pgx.Tx, evidenceID uuid.UUID, p EvidencePatch) error {
	h, err := lockPlannedEvidence(ctx, tx, evidenceID)
	if err != nil {
		return err
	}
	var name *string
	if p.Name != nil {
		n := strings.TrimSpace(*p.Name)
		if n == "" {
			return badInput("missing_name", "la evidencia necesita un nombre")
		}
		name = &n
	}
	if p.Kind != nil {
		if err := checkEvidenceKind(*p.Kind); err != nil {
			return err
		}
	}
	var newScale *string
	var newMax *float64
	setScale := p.ValueScale != nil || p.MaxScore != nil
	if setScale {
		var curScale string
		var curMax *float64
		if err := tx.QueryRow(ctx, `select value_scale, max_score from planned_evidences where id = $1`,
			evidenceID).Scan(&curScale, &curMax); err != nil {
			return err
		}
		scale, max := curScale, curMax
		if p.ValueScale != nil {
			scale = *p.ValueScale
			if scale != curScale {
				max = nil // the old maximum belongs to the old scale
			}
		}
		if p.MaxScore != nil {
			max = p.MaxScore
		}
		s, m, err := resolveEvidenceScale(scale, max)
		if err != nil {
			return err
		}
		newScale, newMax = &s, m
	}
	if p.CriterionIDs != nil {
		ids := dedupe(*p.CriterionIDs)
		if err := checkEvidenceCriteria(ctx, tx, h.ID, ids); err != nil {
			return err
		}
		if err := setEvidenceCriteria(ctx, tx, evidenceID, ids); err != nil {
			return err
		}
	}
	if p.SessionDateSet {
		var entryID *uuid.UUID
		if p.SessionDate != nil {
			id, err := sessionEntryAt(ctx, tx, h.ID, *p.SessionDate)
			if err != nil {
				return err
			}
			entryID = &id
		}
		if err := placeEvidence(ctx, tx, evidenceID, entryID); err != nil {
			return err
		}
	}
	_, err = tx.Exec(ctx, `
		update planned_evidences
		   set name = coalesce($2, name), kind = coalesce($3, kind),
		       value_scale = coalesce($4, value_scale),
		       max_score = case when $4::text is null then max_score else $5::numeric end,
		       accepted_at = coalesce(accepted_at, now())
		 where id = $1
	`, evidenceID, name, p.Kind, newScale, newMax)
	if err != nil {
		return err
	}
	return SyncExperience(ctx, tx, h.ID)
}

// AcceptPlannedEvidence accepts a proposal unchanged.
func AcceptPlannedEvidence(ctx context.Context, tx pgx.Tx, evidenceID uuid.UUID) error {
	h, err := lockPlannedEvidence(ctx, tx, evidenceID)
	if err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, `
		update planned_evidences set accepted_at = coalesce(accepted_at, now()) where id = $1
	`, evidenceID); err != nil {
		return err
	}
	return SyncExperience(ctx, tx, h.ID)
}

// DeletePlannedEvidence soft-deletes a planned evidence, its criterion links
// and its place in the session outline.
func DeletePlannedEvidence(ctx context.Context, tx pgx.Tx, evidenceID uuid.UUID) error {
	h, err := lockPlannedEvidence(ctx, tx, evidenceID)
	if err != nil {
		return err
	}
	for _, q := range []string{
		`update planned_evidence_criteria set deleted_at = now() where evidence_id = $1 and deleted_at is null`,
		`update session_outline_entries set planned_evidence_id = null where planned_evidence_id = $1`,
		`update planned_evidences set deleted_at = now(), session_entry_id = null where id = $1`,
	} {
		if _, err := tx.Exec(ctx, q, evidenceID); err != nil {
			return err
		}
	}
	return SyncExperience(ctx, tx, h.ID)
}

// GetPlannedEvidence returns one planned evidence.
func GetPlannedEvidence(ctx context.Context, tx pgx.Tx, evidenceID uuid.UUID) (ExperienceEvidence, error) {
	var experienceID uuid.UUID
	if err := tx.QueryRow(ctx, `
		select experience_id from planned_evidences where id = $1 and deleted_at is null
	`, evidenceID).Scan(&experienceID); err != nil {
		return ExperienceEvidence{}, err
	}
	list, err := listExperienceEvidences(ctx, tx, experienceID, evidenceID)
	if err != nil {
		return ExperienceEvidence{}, err
	}
	if len(list) == 0 {
		return ExperienceEvidence{}, pgx.ErrNoRows
	}
	return list[0], nil
}

// ------------------------------------------------------- session outline --

type SessionInput struct {
	Title             string
	Topics            *string
	PlannedEvidenceID *uuid.UUID
}

// checkSessionDate requires a class date of the experience: inside its
// range, with a non-cancelled session of the class, and not a non-teaching
// day.
func checkSessionDate(ctx context.Context, tx pgx.Tx, h experienceHeader, date time.Time) error {
	if date.Before(h.StartsOn) || date.After(h.EndsOn) {
		return unprocessable("date_not_in_experience", "esa fecha está fuera de la experiencia")
	}
	n, err := countClassDates(ctx, tx, h.ClassID, date, date)
	if err != nil {
		return err
	}
	if n == 0 {
		return unprocessable("date_not_in_experience", "esa fecha no es un día de clase de esta clase")
	}
	return nil
}

// PutSessionEntry creates or replaces the session entry of a date, and
// accepts it. The body is the entry's whole state: no planned_evidence_id
// empties the session.
func PutSessionEntry(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID, date time.Time, in SessionInput) error {
	h, err := lockExperience(ctx, tx, experienceID)
	if err != nil {
		return err
	}
	title := strings.TrimSpace(in.Title)
	if title == "" {
		return badInput("missing_title", "la sesión necesita un título")
	}
	if err := checkSessionDate(ctx, tx, h, date); err != nil {
		return err
	}
	if in.PlannedEvidenceID != nil {
		var ok bool
		if err := tx.QueryRow(ctx, `
			select exists (
			  select 1 from planned_evidences
			   where id = $1 and experience_id = $2 and deleted_at is null
			)
		`, *in.PlannedEvidenceID, h.ID).Scan(&ok); err != nil {
			return err
		}
		if !ok {
			return unprocessable("evidence_not_in_experience", "esa evidencia no es de esta experiencia")
		}
	}

	topics := trimmedOrNil(in.Topics)
	var entryID uuid.UUID
	err = tx.QueryRow(ctx, `
		update session_outline_entries
		   set title = $3, topics = $4, accepted_at = now()
		 where experience_id = $1 and class_date = $2 and deleted_at is null
		returning id
	`, h.ID, date, title, topics).Scan(&entryID)
	if err == pgx.ErrNoRows {
		err = tx.QueryRow(ctx, `
			insert into session_outline_entries
			  (tenant_id, experience_id, class_date, title, topics, proposed_by, accepted_at)
			values (app.current_tenant_id(), $1, $2, $3, $4, 'teacher', now())
			returning id
		`, h.ID, date, title, topics).Scan(&entryID)
	}
	if err != nil {
		return err
	}

	if in.PlannedEvidenceID != nil {
		err = placeEvidence(ctx, tx, *in.PlannedEvidenceID, &entryID)
	} else {
		err = unplaceEntry(ctx, tx, entryID)
	}
	if err != nil {
		return err
	}
	return SyncExperience(ctx, tx, h.ID)
}

// ProposeSessionEntry writes a session entry the planning agent proposes, on
// a class date of the experience that has none yet. It never touches an
// existing entry (PutSessionEntry would replace it): inserted is false when
// the date already had one. A proposed evidence must be of the experience and
// not yet placed anywhere.
func ProposeSessionEntry(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID, date time.Time, in SessionInput) (inserted bool, err error) {
	h, err := lockExperience(ctx, tx, experienceID)
	if err != nil {
		return false, err
	}
	title := strings.TrimSpace(in.Title)
	if title == "" {
		return false, badInput("missing_title", "la sesión necesita un título")
	}
	if err := checkSessionDate(ctx, tx, h, date); err != nil {
		return false, err
	}
	if in.PlannedEvidenceID != nil {
		var ok bool
		if err := tx.QueryRow(ctx, `
			select exists (
			  select 1 from planned_evidences
			   where id = $1 and experience_id = $2 and deleted_at is null and session_entry_id is null
			)
		`, *in.PlannedEvidenceID, h.ID).Scan(&ok); err != nil {
			return false, err
		}
		if !ok {
			return false, unprocessable("evidence_not_in_experience",
				"esa evidencia no es de esta experiencia o ya está ubicada en otra sesión")
		}
	}
	var entryID uuid.UUID
	err = tx.QueryRow(ctx, `
		insert into session_outline_entries
		  (tenant_id, experience_id, class_date, title, topics, proposed_by, accepted_at)
		values (app.current_tenant_id(), $1, $2, $3, $4, 'mawta', null)
		on conflict (tenant_id, experience_id, class_date) where deleted_at is null do nothing
		returning id
	`, h.ID, date, title, trimmedOrNil(in.Topics)).Scan(&entryID)
	if err == pgx.ErrNoRows {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if in.PlannedEvidenceID != nil {
		if err := placeEvidence(ctx, tx, *in.PlannedEvidenceID, &entryID); err != nil {
			return false, err
		}
	}
	return true, nil
}

func sessionEntryNotFound() error {
	return db.NewAppError(http.StatusNotFound, "not_found", "no hay una sesión planificada en esa fecha")
}

// AcceptSessionEntry accepts a proposed session entry unchanged.
func AcceptSessionEntry(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID, date time.Time) error {
	if _, err := lockExperience(ctx, tx, experienceID); err != nil {
		return err
	}
	tag, err := tx.Exec(ctx, `
		update session_outline_entries set accepted_at = coalesce(accepted_at, now())
		 where experience_id = $1 and class_date = $2 and deleted_at is null
	`, experienceID, date)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return sessionEntryNotFound()
	}
	return SyncExperience(ctx, tx, experienceID)
}

// DeleteSessionEntry soft-deletes the session entry of a date; the evidence
// it held stays in the experience, unplaced.
func DeleteSessionEntry(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID, date time.Time) error {
	if _, err := lockExperience(ctx, tx, experienceID); err != nil {
		return err
	}
	var entryID uuid.UUID
	err := tx.QueryRow(ctx, `
		select id from session_outline_entries
		 where experience_id = $1 and class_date = $2 and deleted_at is null
	`, experienceID, date).Scan(&entryID)
	if err == pgx.ErrNoRows {
		return sessionEntryNotFound()
	}
	if err != nil {
		return err
	}
	if err := unplaceEntry(ctx, tx, entryID); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `update session_outline_entries set deleted_at = now() where id = $1`, entryID); err != nil {
		return err
	}
	// The class session keeps no name the plan gave it.
	if _, err = tx.Exec(ctx, `
		update class_sessions cs set topic = null
		  from learning_experiences le
		 where le.id = $1 and le.status = 'planificada'
		   and cs.class_id = le.class_id and cs.session_date = $2 and cs.deleted_at is null
	`, experienceID, date); err != nil {
		return err
	}
	return SyncExperience(ctx, tx, experienceID)
}

// GetSessionEntry returns the experience's session entry of one date.
func GetSessionEntry(ctx context.Context, tx pgx.Tx, experienceID uuid.UUID, date time.Time) (ExperienceSession, error) {
	list, err := listExperienceSessions(ctx, tx, experienceID, &date)
	if err != nil {
		return ExperienceSession{}, err
	}
	if len(list) == 0 {
		return ExperienceSession{}, sessionEntryNotFound()
	}
	return list[0], nil
}
