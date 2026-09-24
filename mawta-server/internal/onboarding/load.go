package onboarding

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/auth"
)

// Summary is what a load created, for the operator to check and hand over.
// It never carries a password.
type Summary struct {
	Colegio         string
	TenantID        uuid.UUID
	Usuarios        []string
	Periodos        int
	Docentes        int
	Areas           int
	Competencias    int
	Capacidades     int
	Criterios       int
	Aulas           int
	Estudiantes     int
	Clases          int
	Franjas         int
	Sesiones        int
	SesionesConTema int
}

func (s *Summary) String() string {
	var b strings.Builder
	fmt.Fprintf(&b, "Colegio:        %s (%s)\n", s.Colegio, s.TenantID)
	fmt.Fprintf(&b, "Periodos:       %d\n", s.Periodos)
	fmt.Fprintf(&b, "Docentes:       %d (%s)\n", s.Docentes, strings.Join(s.Usuarios, ", "))
	fmt.Fprintf(&b, "Áreas:          %d, con %d competencias, %d capacidades y %d criterios\n", s.Areas, s.Competencias, s.Capacidades, s.Criterios)
	fmt.Fprintf(&b, "Aulas:          %d, con %d estudiantes\n", s.Aulas, s.Estudiantes)
	fmt.Fprintf(&b, "Clases:         %d, con %d franjas de horario\n", s.Clases, s.Franjas)
	fmt.Fprintf(&b, "Sesiones:       %d generadas, %d con tema\n", s.Sesiones, s.SesionesConTema)
	return b.String()
}

// Load writes the whole school inside tx. The caller owns the transaction:
// it commits, or rolls back for a dry run. tx must bypass row security (a
// superuser connection, as cmd/useradd uses): the first users/memberships
// rows of a tenant cannot be written by mawta_app.
//
// Nothing is written unless the file validates and the school does not exist
// yet; any failure part-way leaves the transaction for the caller to roll
// back, so there is never a half-installed school.
func Load(ctx context.Context, tx pgx.Tx, s *Spec, bcryptCost int) (*Summary, error) {
	if err := Validate(s); err != nil {
		return nil, err
	}
	l := &loader{
		ctx:     ctx,
		tx:      tx,
		s:       s,
		mod:     s.Colegio.CodigoModular,
		anio:    fmt.Sprint(s.AnioEscolar.Anio),
		schemes: map[string]uuid.UUID{},
		sum:     &Summary{Colegio: s.Colegio.Nombre},
	}
	l.tenant = ID("tenant", l.mod, "")
	l.year = ID("year", l.mod, l.anio)
	l.sum.TenantID = l.tenant
	l.firstDay = s.AnioEscolar.Periodos[0].Inicio
	for _, p := range s.AnioEscolar.Periodos {
		if p.Inicio < l.firstDay { // ISO dates sort as strings
			l.firstDay = p.Inicio
		}
	}

	if err := l.precheck(); err != nil {
		return nil, err
	}
	steps := []struct {
		name string
		fn   func() error
	}{
		{"colegio y año escolar", l.colegio},
		{"docentes", func() error { return l.docentes(bcryptCost) }},
		{"áreas, competencias y capacidades", l.areas},
		{"aulas y estudiantes", l.aulas},
		{"clases y horario", l.clases},
		{"sesiones", l.sesiones},
	}
	for _, st := range steps {
		if err := st.fn(); err != nil {
			return nil, fmt.Errorf("%s: %w", st.name, err)
		}
	}
	return l.sum, nil
}

type loader struct {
	ctx      context.Context
	tx       pgx.Tx
	s        *Spec
	mod      string // codigo_modular: part of every derived id
	anio     string
	tenant   uuid.UUID
	year     uuid.UUID
	firstDay string // earliest periodo start: when titulars and horarios begin
	schemes  map[string]uuid.UUID
	sum      *Summary
}

func (l *loader) exec(sql string, args ...any) error {
	_, err := l.tx.Exec(l.ctx, sql, args...)
	return err
}

// nz turns an empty optional value into SQL NULL.
func nz(s string) *string {
	if strings.TrimSpace(s) == "" {
		return nil
	}
	return &s
}

// precheck refuses a school or an account that already exists, before
// writing anything, with a message about the file rather than a constraint.
func (l *loader) precheck() error {
	var exists bool
	if err := l.tx.QueryRow(l.ctx,
		`select exists (select 1 from tenants where modular_code = $1 and deleted_at is null)`,
		l.mod).Scan(&exists); err != nil {
		return err
	}
	if exists {
		return Errors{fmt.Sprintf("colegio.codigo_modular: el colegio %s ya existe en esta base. Este cargador solo instala colegios nuevos y no modificó nada.", l.mod)}
	}

	usuarios := make([]string, len(l.s.Docentes))
	emails := make([]string, len(l.s.Docentes))
	for i, d := range l.s.Docentes {
		usuarios[i] = strings.ToLower(d.Usuario)
		emails[i] = strings.ToLower(strings.TrimSpace(d.Email))
	}
	rows, err := l.tx.Query(l.ctx, `
		select coalesce(lower(username), ''), lower(email) from users
		 where deleted_at is null and (lower(username) = any($1) or lower(email) = any($2))`,
		usuarios, emails)
	if err != nil {
		return err
	}
	defer rows.Close()
	var errs Errors
	for rows.Next() {
		var u, e string
		if err := rows.Scan(&u, &e); err != nil {
			return err
		}
		for i := range usuarios {
			path := fmt.Sprintf("docentes[%d]", i)
			if u != "" && u == usuarios[i] {
				errs = append(errs, fmt.Sprintf("%s.usuario: %q ya existe en Mawta; elige otro", path, usuarios[i]))
			}
			if e == emails[i] {
				errs = append(errs, fmt.Sprintf("%s.email: %q ya está registrado en Mawta; una persona solo puede pertenecer a un colegio", path, emails[i]))
			}
		}
	}
	if err := rows.Err(); err != nil {
		return err
	}
	if len(errs) > 0 {
		sort.Strings(errs)
		return errs
	}
	return nil
}

// ------------------------------------------------------------ colegio, año --

func (l *loader) colegio() error {
	c := l.s.Colegio
	tz := c.ZonaHoraria
	if tz == "" {
		tz = "America/Lima"
	}
	if err := l.exec(`
		insert into tenants (id, name, legal_name, modular_code, kind, city, region, timezone,
		                     uses_internal_grading, status)
		values ($1, $2, $3, $4, $5, $6, $7, $8, true, 'active')`,
		l.tenant, c.Nombre, nz(c.RazonSocial), c.CodigoModular, c.Tipo, nz(c.Ciudad), nz(c.Region), tz); err != nil {
		return err
	}

	a := l.s.AnioEscolar
	if err := l.exec(`
		insert into academic_years (id, tenant_id, year, name, starts_on, ends_on, term_structure, status)
		values ($1, $2, $3, $4, $5::text::date, $6::text::date, $7, 'active')`,
		l.year, l.tenant, a.Anio, a.Nombre, a.Inicio, a.Fin, a.Estructura); err != nil {
		return err
	}
	// Every periodo goes in 'active', including past ones: the
	// sync_score_denormalised trigger rejects any score aimed at a closed
	// term, so a periodo is only closed once its evidence is in.
	for _, p := range a.Periodos {
		if err := l.exec(`
			insert into terms (id, tenant_id, academic_year_id, stage, sequence, name, short_name,
			                   starts_on, ends_on, status, grades_due_on)
			values ($1, $2, $3, null, $4, $5, $6, $7::text::date, $8::text::date, 'active', $9::text::date)`,
			l.termID(p), l.tenant, l.year, p.Numero, p.Nombre, nz(p.Abreviatura), p.Inicio, p.Fin,
			nz(p.FechaEntregaNotas)); err != nil {
			return err
		}
		l.sum.Periodos++
	}
	return nil
}

func (l *loader) termID(p Periodo) uuid.UUID {
	return ID("term", l.mod, fmt.Sprintf("%s:%d", l.anio, p.Numero))
}

// --------------------------------------------------------------- docentes --

// docentes hashes each password with the same bcrypt path as the login, in
// this same transaction: there is no placeholder hash and no second step
// that could fail after the school is already committed.
func (l *loader) docentes(bcryptCost int) error {
	for _, d := range l.s.Docentes {
		hash, err := auth.HashPassword(d.Clave, bcryptCost)
		if err != nil {
			return fmt.Errorf("docente %s: %w", d.Usuario, err)
		}
		display := d.NombreVisible
		if strings.TrimSpace(display) == "" {
			display = d.Nombres + " " + d.Apellidos
		}
		userID := ID("user", l.mod, d.Usuario)
		membershipID := ID("membership", l.mod, d.Usuario)
		if err := l.exec(`
			insert into users (id, email, given_name, family_name, display_name, status, username,
			                   password_hash, password_changed_at, failed_login_count)
			values ($1, lower($2), $3, $4, $5, 'active', $6, $7, now(), 0)`,
			userID, strings.TrimSpace(d.Email), d.Nombres, d.Apellidos, display, d.Usuario, hash); err != nil {
			return fmt.Errorf("docente %s: %w", d.Usuario, err)
		}
		if err := l.exec(`
			insert into memberships (id, tenant_id, user_id, role, status, joined_at)
			values ($1, $2, $3, 'teacher', 'active', now())`,
			membershipID, l.tenant, userID); err != nil {
			return fmt.Errorf("docente %s: %w", d.Usuario, err)
		}
		if err := l.exec(`
			insert into teachers (id, tenant_id, membership_id, employee_code, display_name, title,
			                      hired_on, status)
			values ($1, $2, $3, $4, $5, $6, $7::text::date, 'active')`,
			l.teacherID(d.Usuario), l.tenant, membershipID, nz(d.CodigoEmpleado), display, nz(d.Cargo),
			nz(d.FechaIngreso)); err != nil {
			return fmt.Errorf("docente %s: %w", d.Usuario, err)
		}
		l.sum.Docentes++
		l.sum.Usuarios = append(l.sum.Usuarios, d.Usuario)
	}
	return nil
}

func (l *loader) teacherID(usuario string) uuid.UUID { return ID("teacher", l.mod, usuario) }

// ------------------------------------------------------------------ áreas --

func (l *loader) areas() error {
	if err := l.scales(); err != nil {
		return err
	}
	for i, a := range l.s.Areas {
		subjectID := ID("subject", l.mod, a.Codigo)
		if err := l.exec(`
			insert into subjects (id, tenant_id, code, name, area_curricular, icon_key, is_tutoria, sort_order)
			values ($1, $2, $3, $4, $4, $5, $6, $7)`,
			subjectID, l.tenant, a.Codigo, a.Nombre, nz(a.Icono), a.EsTutoria, i+1); err != nil {
			return fmt.Errorf("área %s: %w", a.Codigo, err)
		}
		l.sum.Areas++
		for j, c := range a.Competencias {
			kind := c.Tipo
			if kind == "" {
				kind = "area"
			}
			if err := l.competencia(c, &subjectID, kind, j+1); err != nil {
				return err
			}
		}
		if err := l.scheme(a); err != nil {
			return fmt.Errorf("esquema de %s: %w", a.Codigo, err)
		}
	}
	// Transversales hang off no área and no single teacher, and never count
	// toward promotion; competencies_transversal_has_no_subject needs the
	// null subject.
	for j, c := range l.s.CompetenciasTransversales {
		if err := l.competencia(c, nil, "transversal", j+1); err != nil {
			return err
		}
	}
	return nil
}

func (l *loader) competencia(c Competencia, subjectID *uuid.UUID, kind string, order int) error {
	compID := ID("competency", l.mod, c.Codigo)
	if err := l.exec(`
		insert into competencies (id, tenant_id, subject_id, code, name, kind, sort_order, is_active)
		values ($1, $2, $3, $4, $5, $6, $7, true)`,
		compID, l.tenant, subjectID, c.Codigo, c.Nombre, kind, order); err != nil {
		return fmt.Errorf("competencia %s: %w", c.Codigo, err)
	}
	l.sum.Competencias++
	for k, cap := range c.Capacidades {
		capID := ID("capability", l.mod, cap.Codigo)
		if err := l.exec(`
			insert into capabilities (id, tenant_id, competency_id, code, name, sort_order)
			values ($1, $2, $3, $4, $5, $6)`,
			capID, l.tenant, compID, cap.Codigo, cap.Nombre, k+1); err != nil {
			return fmt.Errorf("capacidad %s: %w", cap.Codigo, err)
		}
		l.sum.Capacidades++
		for m, cr := range cap.Criterios {
			if err := l.exec(`
				insert into evaluation_criteria (id, tenant_id, competency_id, capability_id, code,
				                                 description, sort_order)
				values ($1, $2, $3, $4, $5, $6, $7)`,
				ID("criterion", l.mod, cr.Codigo), l.tenant, compID, capID, cr.Codigo, cr.Descripcion, m+1); err != nil {
				return fmt.Errorf("criterio %s: %w", cr.Codigo, err)
			}
			l.sum.Criterios++
		}
	}
	return nil
}

// scales creates the two scales every school needs. They are different in
// kind, not just in range: AD/A/B/C are levels of achievement (the only thing
// that goes to SIAGIE), the vigesimal 0-20 feeds the school's internal
// average and is never the official record.
func (l *loader) scales() error {
	if err := l.exec(`
		insert into grade_scales (id, tenant_id, code, name, kind, min_value, max_value, decimals)
		values ($1, $3, $4, 'Escala MINEDU AD/A/B/C', 'ordinal', 1, 4, 0),
		       ($2, $3, $5, 'Sistema interno vigesimal', 'numeric', 0, 20, 0)`,
		ID("scale", l.mod, scaleMinedu), ID("scale", l.mod, scaleVigesimal), l.tenant,
		scaleMinedu, scaleVigesimal); err != nil {
		return err
	}
	for _, lv := range mineduLevels {
		if err := l.exec(`
			insert into grade_scale_levels (id, tenant_id, scale_id, code, label, short_label, ordinal,
			                                min_normalized, max_normalized, color_key)
			values ($1, $2, $3, $4, $5, $4, $6, $7, $8, $9)`,
			ID("scale_level", l.mod, scaleMinedu+":"+lv.code), l.tenant, ID("scale", l.mod, scaleMinedu),
			lv.code, lv.label, lv.ordinal, lv.minNorm, lv.maxNorm, lv.colorKey); err != nil {
			return err
		}
	}
	return nil
}

// scheme creates the área's grading scheme. The order is forced by the
// triggers: check_publishable (a plain BEFORE trigger) looks for the weights
// the moment published_at is written, so the version goes in unpublished, the
// weights follow, and an UPDATE publishes it.
func (l *loader) scheme(a Area) error {
	s := schemeFor(a)
	schemeID := ID("scheme", l.mod, s.Codigo)
	versionID := ID("scheme_version", l.mod, s.Codigo+":1")
	if err := l.exec(`
		insert into grading_schemes (id, tenant_id, scale_id, code, name, description, is_active)
		values ($1, $2, $3, $4, $5, $6, true)`,
		schemeID, l.tenant, ID("scale", l.mod, scaleVigesimal), s.Codigo, s.Nombre, nz(s.Descripcion)); err != nil {
		return err
	}
	// effective_from is 1 January, so the version governs even the earliest
	// periodo of the year; class_effective_grading_schemes resolves nothing
	// for a term that starts before it. The retake cap of 0.70 (= A) keeps a
	// recuperación from producing an AD; nothing partial shows until 20% of
	// the term's weight is evaluated.
	if err := l.exec(`
		insert into grading_scheme_versions (id, tenant_id, scheme_id, version, effective_from,
		       rounding_mode, rounding_decimals, absent_counts_as, retake_policy,
		       retake_cap_normalized, min_evaluated_weight_for_grade, notes)
		values ($1, $2, $3, 1, make_date($4, 1, 1), 'half_up', 0, 'zero', 'capped', 0.70, 0.20, $5)`,
		versionID, l.tenant, schemeID, l.s.AnioEscolar.Anio,
		"Vigente todo el "+strings.ToLower(l.s.AnioEscolar.Nombre)+"."); err != nil {
		return err
	}
	for i, c := range s.Componentes {
		componentID := ID("component", l.mod, s.Codigo+":"+c.Codigo)
		if err := l.exec(`
			insert into grading_components (id, tenant_id, scheme_id, code, name, sort_order)
			values ($1, $2, $3, $4, $5, $6)`,
			componentID, l.tenant, schemeID, c.Codigo, c.Nombre, i+1); err != nil {
			return err
		}
		if err := l.exec(`
			insert into grading_scheme_component_weights (tenant_id, scheme_version_id, component_id,
			       weight, drop_lowest_n, aggregation, is_required)
			values ($1, $2, $3, round($4::numeric, 6), $5, 'weighted_mean', true)`,
			l.tenant, versionID, componentID, c.Peso, c.DescartarMasBajas); err != nil {
			return err
		}
	}
	if err := l.exec(`update grading_scheme_versions set published_at = now() where id = $1`, versionID); err != nil {
		return err
	}
	l.schemes[a.Codigo] = schemeID
	return nil
}

// ------------------------------------------------------------------ aulas --

func (l *loader) aulas() error {
	for _, g := range l.s.Grados {
		if err := l.exec(`
			insert into grade_levels (id, tenant_id, code, label, long_label, stage, cycle, ordinal)
			values ($1, $2, $3, $4, $5, $6, null, $7)`,
			ID("grade", l.mod, g.Codigo), l.tenant, g.Codigo, g.Etiqueta, g.NombreLargo, g.Nivel, g.Orden); err != nil {
			return fmt.Errorf("grado %s: %w", g.Codigo, err)
		}
	}
	for _, a := range l.s.Aulas {
		var tutor *uuid.UUID
		if a.Tutor != "" {
			t := l.teacherID(a.Tutor)
			tutor = &t
		}
		turno := a.Turno
		if turno == "" {
			turno = "manana"
		}
		var capacidad *int
		if a.Capacidad > 0 {
			capacidad = &a.Capacidad
		}
		sectionID := l.sectionID(a.Key())
		if err := l.exec(`
			insert into sections (id, tenant_id, academic_year_id, grade_level_id, label, name,
			                      tutor_teacher_id, shift, capacity, status)
			values ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'active')`,
			sectionID, l.tenant, l.year, ID("grade", l.mod, a.Grado), a.Seccion, a.Nombre,
			tutor, turno, capacidad); err != nil {
			return fmt.Errorf("aula %s: %w", a.Key(), err)
		}
		l.sum.Aulas++
		for _, e := range a.Estudiantes {
			if err := l.estudiante(e, sectionID); err != nil {
				return fmt.Errorf("aula %s, estudiante %s: %w", a.Key(), e.Codigo, err)
			}
		}
	}
	return nil
}

func (l *loader) sectionID(aulaKey string) uuid.UUID {
	return ID("section", l.mod, l.anio+":"+aulaKey)
}

func (l *loader) estudiante(e Estudiante, sectionID uuid.UUID) error {
	matricula := e.FechaMatricula
	if matricula == "" {
		matricula = l.s.AnioEscolar.Inicio
	}
	studentID := ID("student", l.mod, e.Codigo)
	if err := l.exec(`
		insert into students (id, tenant_id, student_code, siagie_code, given_name, paternal_surname,
		                      maternal_surname, preferred_name, birthdate, sex, document_type,
		                      document_number, enrolled_on, status, inclusion_support)
		values ($1, $2, $3, $4, $5, $6, $7, $8, $9::text::date, $10, $11, $12, $13::text::date,
		        'active', $14)`,
		studentID, l.tenant, e.Codigo, nz(e.CodigoSiagie), e.Nombres, e.ApellidoPaterno,
		nz(e.ApellidoMaterno), nz(e.NombrePreferido), nz(e.FechaNacimiento), nz(e.Sexo),
		nz(e.TipoDocumento), nz(e.NumeroDocumento), matricula, e.ApoyoInclusion); err != nil {
		return err
	}
	// The roster of a class is derived from section_memberships, so every
	// class in this aula shares these students without duplicating a row.
	if err := l.exec(`
		insert into section_memberships (tenant_id, student_id, section_id, academic_year_id,
		                                 joined_on, status)
		values ($1, $2, $3, $4, $5::text::date, 'active')`,
		l.tenant, studentID, sectionID, l.year, matricula); err != nil {
		return err
	}
	l.sum.Estudiantes++
	return nil
}

// ----------------------------------------------------------------- clases --

func (l *loader) clases() error {
	aulas := map[string]Aula{}
	for _, a := range l.s.Aulas {
		aulas[a.Key()] = a
	}
	areas := map[string]Area{}
	for _, a := range l.s.Areas {
		areas[a.Codigo] = a
	}
	grados := map[string]Grado{}
	for _, g := range l.s.Grados {
		grados[g.Codigo] = g
	}
	courses := map[string]bool{}

	for _, c := range l.s.Clases {
		aula := aulas[c.Aula]
		area := areas[c.Area]
		gradeID := ID("grade", l.mod, aula.Grado)

		// One course per área and grado; every class of that pair shares it.
		courseKey := l.anio + ":" + c.Area + ":" + aula.Grado
		courseID := ID("course", l.mod, courseKey)
		if !courses[courseKey] {
			var horas *float64
			if c.HorasSemanales > 0 {
				horas = &c.HorasSemanales
			}
			if err := l.exec(`
				insert into courses (id, tenant_id, academic_year_id, subject_id, grade_level_id, name,
				                     weekly_hours, grading_scheme_id)
				values ($1, $2, $3, $4, $5, $6, $7, $8)`,
				courseID, l.tenant, l.year, ID("subject", l.mod, c.Area), gradeID,
				area.Nombre+" "+grados[aula.Grado].Etiqueta, horas, l.schemes[c.Area]); err != nil {
				return fmt.Errorf("curso %s %s: %w", c.Area, aula.Grado, err)
			}
			courses[courseKey] = true
		}

		classID := l.classID(c.Codigo)
		if err := l.exec(`
			insert into classes (id, tenant_id, academic_year_id, grade_level_id, course_id, section_id,
			                     name, code, default_room, status)
			values ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'active')`,
			classID, l.tenant, l.year, gradeID, courseID, l.sectionID(c.Aula),
			c.Nombre, c.Codigo, nz(c.Salon)); err != nil {
			return fmt.Errorf("clase %s: %w", c.Codigo, err)
		}
		if err := l.exec(`
			insert into class_teachers (tenant_id, class_id, teacher_id, role, starts_on)
			values ($1, $2, $3, 'titular', $4::text::date)`,
			l.tenant, classID, l.teacherID(c.Docente), l.firstDay); err != nil {
			return fmt.Errorf("clase %s: %w", c.Codigo, err)
		}
		l.sum.Clases++

		for _, f := range c.Horario {
			dia, _ := parseWeekday(f.Dia)
			if err := l.exec(`
				insert into class_schedules (id, tenant_id, class_id, weekday, starts_at, ends_at, room,
				                             effective_from)
				values ($1, $2, $3, $4, $5::text::time, $6::text::time, $7, $8::text::date)`,
				l.scheduleID(c.Codigo, dia, f.Inicio), l.tenant, classID, dia, clock(f.Inicio), clock(f.Fin),
				nz(roomFor(c, f)), l.firstDay); err != nil {
				return fmt.Errorf("clase %s, franja %s %s: %w", c.Codigo, f.Dia, f.Inicio, err)
			}
			l.sum.Franjas++
		}
	}
	return nil
}

func (l *loader) classID(codigo string) uuid.UUID { return ID("class", l.mod, l.anio+":"+codigo) }

func (l *loader) scheduleID(claseCodigo string, dia int, inicio string) uuid.UUID {
	return ID("schedule", l.mod, fmt.Sprintf("%s:%s:%d:%s", l.anio, claseCodigo, dia, clock(inicio)))
}

// clock normalises "8:00" to "08:00" so it is stable inside a derived id.
func clock(s string) string {
	m, _ := parseClock(s)
	return fmt.Sprintf("%02d:%02d", m/60, m%60)
}

func roomFor(c Clase, f Franja) string {
	if strings.TrimSpace(f.Salon) != "" {
		return f.Salon
	}
	return c.Salon
}

// ---------------------------------------------------------------- sesiones --

// sesiones materialises the lessons. The app only ever reads class_sessions,
// it never creates them, so without this a freshly loaded teacher would see
// no lesson at all. One session per horario franja per matching date inside
// each periodo, all 'scheduled'; the time zone conversion is Postgres' so the
// dates line up with how the app computes "today" in the school's zone.
func (l *loader) sesiones() error {
	tz := l.s.Colegio.ZonaHoraria
	if tz == "" {
		tz = "America/Lima"
	}
	for _, c := range l.s.Clases {
		classID := l.classID(c.Codigo)
		for _, f := range c.Horario {
			dia, _ := parseWeekday(f.Dia)
			for _, p := range l.s.AnioEscolar.Periodos {
				tag, err := l.tx.Exec(l.ctx, `
					insert into class_sessions (id, tenant_id, academic_year_id, class_id, schedule_id,
					       term_id, session_date, scheduled_start_at, scheduled_end_at, status, room)
					select md5($1 || g.d::date::text || ':' || $2)::uuid, $3, $4, $5, $6, $7, g.d::date,
					       (g.d::date + $8::text::time) at time zone $9,
					       (g.d::date + $10::text::time) at time zone $9,
					       'scheduled', $11
					  from generate_series($12::text::date, $13::text::date, interval '1 day') as g(d)
					 where extract(isodow from g.d) = $14`,
					fmt.Sprintf("session:%s:%s:%s:", l.mod, l.anio, c.Codigo), clock(f.Inicio),
					l.tenant, l.year, classID, l.scheduleID(c.Codigo, dia, f.Inicio), l.termID(p),
					clock(f.Inicio), tz, clock(f.Fin), nz(roomFor(c, f)), p.Inicio, p.Fin, dia)
				if err != nil {
					return fmt.Errorf("clase %s: %w", c.Codigo, err)
				}
				l.sum.Sesiones += int(tag.RowsAffected())
			}
		}
		// A tema names the first session of its date: when a class meets
		// twice on one day, the first block is the one the plan refers to.
		for _, s := range c.Sesiones {
			tag, err := l.tx.Exec(l.ctx, `
				update class_sessions set topic = $3
				 where id = (select id from class_sessions
				              where class_id = $1 and session_date = $2::text::date
				              order by scheduled_start_at limit 1)`,
				classID, s.Fecha, strings.TrimSpace(s.Tema))
			if err != nil {
				return fmt.Errorf("clase %s, sesión %s: %w", c.Codigo, s.Fecha, err)
			}
			if tag.RowsAffected() != 1 {
				return fmt.Errorf("clase %s: no hay sesión el %s para ponerle el tema %q", c.Codigo, s.Fecha, s.Tema)
			}
			l.sum.SesionesConTema++
		}
	}
	return nil
}
