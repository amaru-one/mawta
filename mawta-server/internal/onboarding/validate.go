package onboarding

import (
	"fmt"
	"math"
	"regexp"
	"sort"
	"strings"
	"time"
	_ "time/tzdata" // the api image is debian-slim without tzdata; zona_horaria must still validate

	"mawta-server/internal/auth"
)

// Errors is every problem found in a file, one line each, prefixed with the
// JSON path of the offending value. The onboarding team fixes them all in one
// pass instead of rerunning the loader once per mistake.
type Errors []string

func (e Errors) Error() string { return strings.Join(e, "\n") }

var (
	reModular  = regexp.MustCompile(`^[0-9]{7}$`)
	reUsername = regexp.MustCompile(`^[a-z0-9._-]{3,64}$`)
	reSiagie   = regexp.MustCompile(`^[0-9]{14}$`)
	reDNI      = regexp.MustCompile(`^[0-9]{8}$`)
)

var weekdays = map[string]int{
	"lunes": 1, "martes": 2, "miercoles": 3, "jueves": 4,
	"viernes": 5, "sabado": 6, "domingo": 7,
}

var weekdayNames = []string{"", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"}

// maxPeriodos is how many periodos each estructura allows.
var maxPeriodos = map[string]int{"bimestre": 4, "trimestre": 3, "semestre": 2}

// Validate checks everything that can be checked without a database: formats,
// allowed values, every cross-reference, date ranges, overlapping horarios.
// Most of these the schema enforces too, but a Postgres constraint name means
// nothing to the person who filled in the file.
func Validate(s *Spec) error {
	v := &checker{}
	v.colegio(s.Colegio)
	periodos := v.anio(s.AnioEscolar)
	docentes := v.docentes(s.Docentes)
	areas := v.areas(s.Areas, s.CompetenciasTransversales)
	grados := v.grados(s.Grados)
	aulas := v.aulas(s.Aulas, grados, docentes, s.AnioEscolar)
	v.clases(s.Clases, areas, aulas, docentes, periodos)
	if len(v.errs) > 0 {
		return v.errs
	}
	return nil
}

type checker struct {
	errs Errors
}

func (v *checker) addf(path, format string, args ...any) {
	v.errs = append(v.errs, path+": "+fmt.Sprintf(format, args...))
}

// isPlaceholder spots template text left unfilled, like "<nombre del colegio>".
func isPlaceholder(s string) bool {
	s = strings.TrimSpace(s)
	return strings.HasPrefix(s, "<") && strings.HasSuffix(s, ">")
}

// required reports whether value is filled in, recording an error if not.
func (v *checker) required(path, value string) bool {
	switch {
	case strings.TrimSpace(value) == "":
		v.addf(path, "es obligatorio")
		return false
	case isPlaceholder(value):
		v.addf(path, "falta completar (todavía dice %q)", value)
		return false
	}
	return true
}

// optional reports whether value is filled in; empty is fine, a leftover
// placeholder is not.
func (v *checker) optional(path, value string) bool {
	if isPlaceholder(value) {
		v.addf(path, "falta completar o dejar vacío (todavía dice %q)", value)
		return false
	}
	return strings.TrimSpace(value) != ""
}

func (v *checker) oneOf(path, value string, allowed ...string) {
	for _, a := range allowed {
		if value == a {
			return
		}
	}
	v.addf(path, "%q no es válido; usa uno de: %s", value, strings.Join(allowed, ", "))
}

func parseDate(s string) (time.Time, error) { return time.Parse("2006-01-02", strings.TrimSpace(s)) }

func (v *checker) date(path, value string) (time.Time, bool) {
	if !v.required(path, value) {
		return time.Time{}, false
	}
	d, err := parseDate(value)
	if err != nil {
		v.addf(path, "%q no es una fecha válida; usa el formato AAAA-MM-DD, por ejemplo 2026-03-02", value)
		return time.Time{}, false
	}
	return d, true
}

func (v *checker) optionalDate(path, value string) (time.Time, bool) {
	if !v.optional(path, value) {
		return time.Time{}, false
	}
	return v.date(path, value)
}

// parseClock turns "08:00" into minutes since midnight.
func parseClock(s string) (int, error) {
	t, err := time.Parse("15:04", strings.TrimSpace(s))
	if err != nil {
		return 0, err
	}
	return t.Hour()*60 + t.Minute(), nil
}

func (v *checker) clock(path, value string) (int, bool) {
	if !v.required(path, value) {
		return 0, false
	}
	m, err := parseClock(value)
	if err != nil {
		v.addf(path, "%q no es una hora válida; usa HH:MM en formato de 24 horas, por ejemplo 08:00 o 14:30", value)
		return 0, false
	}
	return m, true
}

// parseWeekday accepts "lunes", "Miércoles", "sabado" and returns ISO 1..7.
func parseWeekday(s string) (int, bool) {
	s = strings.ToLower(strings.TrimSpace(s))
	s = strings.NewReplacer("á", "a", "é", "e", "í", "i", "ó", "o", "ú", "u").Replace(s)
	d, ok := weekdays[s]
	return d, ok
}

// unique records value under scope and reports a duplicate.
func (v *checker) unique(seen map[string]string, path, what, value string) {
	if value == "" {
		return
	}
	if first, dup := seen[value]; dup {
		v.addf(path, "%s %q está repetido (ya aparece en %s)", what, value, first)
		return
	}
	seen[value] = path
}

// ---------------------------------------------------------------- colegio --

func (v *checker) colegio(c Colegio) {
	v.required("colegio.nombre", c.Nombre)
	v.optional("colegio.razon_social", c.RazonSocial)
	if v.required("colegio.codigo_modular", c.CodigoModular) && !reModular.MatchString(c.CodigoModular) {
		v.addf("colegio.codigo_modular", "%q debe tener exactamente 7 dígitos (código modular MINEDU)", c.CodigoModular)
	}
	if v.required("colegio.tipo", c.Tipo) {
		v.oneOf("colegio.tipo", c.Tipo, "publica", "privada", "parroquial", "internacional")
	}
	v.optional("colegio.ciudad", c.Ciudad)
	v.optional("colegio.region", c.Region)
	if v.optional("colegio.zona_horaria", c.ZonaHoraria) {
		if _, err := time.LoadLocation(c.ZonaHoraria); err != nil || c.ZonaHoraria == "Local" {
			v.addf("colegio.zona_horaria", "%q no es una zona horaria IANA; en Perú es America/Lima", c.ZonaHoraria)
		}
	}
}

// ------------------------------------------------------------ año escolar --

type periodoRange struct {
	numero      int
	inicio, fin time.Time
}

func (v *checker) anio(a AnioEscolar) []periodoRange {
	if a.Anio < 2000 || a.Anio > 2100 {
		v.addf("anio_escolar.anio", "%d no es un año válido", a.Anio)
	}
	v.required("anio_escolar.nombre", a.Nombre)
	inicio, okI := v.date("anio_escolar.inicio", a.Inicio)
	fin, okF := v.date("anio_escolar.fin", a.Fin)
	if okI && okF && !fin.After(inicio) {
		v.addf("anio_escolar.fin", "debe ser posterior a anio_escolar.inicio")
	}
	if okI && inicio.Year() != a.Anio {
		v.addf("anio_escolar.inicio", "%s no cae en el año %d", a.Inicio, a.Anio)
	}
	max := 6
	if v.required("anio_escolar.estructura", a.Estructura) {
		v.oneOf("anio_escolar.estructura", a.Estructura, "bimestre", "trimestre", "semestre")
		if m, ok := maxPeriodos[a.Estructura]; ok {
			max = m
		}
	}

	if len(a.Periodos) == 0 {
		v.addf("anio_escolar.periodos", "debe haber al menos un periodo (bimestre, trimestre o semestre) con su horario")
		return nil
	}
	var out []periodoRange
	numeros := map[string]string{}
	for i, p := range a.Periodos {
		path := fmt.Sprintf("anio_escolar.periodos[%d]", i)
		if p.Numero < 1 || p.Numero > max {
			v.addf(path+".numero", "%d no es válido; con estructura %q va de 1 a %d", p.Numero, a.Estructura, max)
		}
		v.unique(numeros, path+".numero", "el número de periodo", fmt.Sprint(p.Numero))
		v.required(path+".nombre", p.Nombre)
		v.optional(path+".abreviatura", p.Abreviatura)
		pi, okPI := v.date(path+".inicio", p.Inicio)
		pf, okPF := v.date(path+".fin", p.Fin)
		v.optionalDate(path+".fecha_entrega_notas", p.FechaEntregaNotas)
		if !okPI || !okPF {
			continue
		}
		if !pf.After(pi) {
			v.addf(path+".fin", "debe ser posterior a %s.inicio", path)
			continue
		}
		if okI && okF && (pi.Before(inicio) || pf.After(fin)) {
			v.addf(path, "del %s al %s se sale del año escolar (%s a %s)", p.Inicio, p.Fin, a.Inicio, a.Fin)
		}
		for j, prev := range out {
			// Both ends inclusive, as terms_no_overlap compares them: T-I
			// ending 29-05 and T-II starting 29-05 is an overlap.
			if !pi.After(prev.fin) && !prev.inicio.After(pf) {
				v.addf(path, "se superpone con anio_escolar.periodos[%d]; un periodo debe empezar después del día en que termina el anterior", j)
			}
		}
		out = append(out, periodoRange{numero: p.Numero, inicio: pi, fin: pf})
	}
	return out
}

// --------------------------------------------------------------- docentes --

func (v *checker) docentes(ds []Docente) map[string]bool {
	known := map[string]bool{}
	if len(ds) == 0 {
		v.addf("docentes", "debe haber al menos un docente")
	}
	usuarios, emails, codigos := map[string]string{}, map[string]string{}, map[string]string{}
	for i, d := range ds {
		path := fmt.Sprintf("docentes[%d]", i)
		if v.required(path+".usuario", d.Usuario) {
			if !reUsername.MatchString(d.Usuario) {
				v.addf(path+".usuario", "%q solo puede tener minúsculas, números, punto, guion o guion bajo, entre 3 y 64 caracteres", d.Usuario)
			}
			v.unique(usuarios, path+".usuario", "el usuario", d.Usuario)
			known[d.Usuario] = true
		}
		if v.required(path+".clave", d.Clave) && auth.ValidatePassword(d.Clave) != nil {
			v.addf(path+".clave", "debe tener entre %d y %d caracteres (tiene %d)", auth.MinPasswordLen, auth.MaxPasswordLen, len(d.Clave))
		}
		if v.required(path+".email", d.Email) {
			if !strings.Contains(d.Email, "@") {
				v.addf(path+".email", "%q no parece un correo", d.Email)
			}
			v.unique(emails, path+".email", "el correo", strings.ToLower(strings.TrimSpace(d.Email)))
		}
		v.required(path+".nombres", d.Nombres)
		v.required(path+".apellidos", d.Apellidos)
		v.optional(path+".nombre_visible", d.NombreVisible)
		v.optional(path+".cargo", d.Cargo)
		if v.optional(path+".codigo_empleado", d.CodigoEmpleado) {
			v.unique(codigos, path+".codigo_empleado", "el código de empleado", d.CodigoEmpleado)
		}
		v.optionalDate(path+".fecha_ingreso", d.FechaIngreso)
	}
	return known
}

// ------------------------------------------------------------------ áreas --

func (v *checker) areas(as []Area, transversales []Competencia) map[string]bool {
	known := map[string]bool{}
	if len(as) == 0 {
		v.addf("areas", "debe haber al menos un área")
	}
	areaCodes, schemeCodes := map[string]string{}, map[string]string{}
	// Competencia, capacidad and criterio codes are unique across the whole
	// school, not just within their parent: seed_demo.sql and every report
	// find them by code alone.
	comps, caps, crits := map[string]string{}, map[string]string{}, map[string]string{}
	for i, a := range as {
		path := fmt.Sprintf("areas[%d]", i)
		if v.required(path+".codigo", a.Codigo) {
			v.unique(areaCodes, path+".codigo", "el código de área", a.Codigo)
			known[a.Codigo] = true
		}
		v.required(path+".nombre", a.Nombre)
		v.optional(path+".icono", a.Icono)
		if len(a.Competencias) == 0 {
			v.addf(path+".competencias", "el área debe tener al menos una competencia")
		}
		for j, c := range a.Competencias {
			cpath := fmt.Sprintf("%s.competencias[%d]", path, j)
			if c.Tipo != "" {
				v.oneOf(cpath+".tipo", c.Tipo, "area", "adicional_area")
			}
			v.competencia(cpath, c, comps, caps, crits)
		}
		s := schemeFor(a)
		spath := path + ".esquema_calificacion"
		if a.EsquemaCalificacion == nil {
			spath = path + " (esquema estándar)"
		}
		v.esquema(spath, s, schemeCodes)
	}
	for i, c := range transversales {
		cpath := fmt.Sprintf("competencias_transversales[%d]", i)
		if c.Tipo != "" && c.Tipo != "transversal" {
			v.addf(cpath+".tipo", "las competencias transversales no llevan tipo (o llevan \"transversal\")")
		}
		v.competencia(cpath, c, comps, caps, crits)
	}
	return known
}

func (v *checker) competencia(path string, c Competencia, comps, caps, crits map[string]string) {
	if v.required(path+".codigo", c.Codigo) {
		v.unique(comps, path+".codigo", "el código de competencia", c.Codigo)
	}
	v.required(path+".nombre", c.Nombre)
	// A criterio must hang off a capacidad (evaluation_criteria.capability_id
	// is NOT NULL), so a competencia without capacidades can never be assessed.
	if len(c.Capacidades) == 0 {
		v.addf(path+".capacidades", "la competencia debe tener al menos una capacidad")
	}
	for k, cap := range c.Capacidades {
		kpath := fmt.Sprintf("%s.capacidades[%d]", path, k)
		if v.required(kpath+".codigo", cap.Codigo) {
			v.unique(caps, kpath+".codigo", "el código de capacidad", cap.Codigo)
		}
		v.required(kpath+".nombre", cap.Nombre)
		for m, cr := range cap.Criterios {
			mpath := fmt.Sprintf("%s.criterios[%d]", kpath, m)
			if v.required(mpath+".codigo", cr.Codigo) {
				v.unique(crits, mpath+".codigo", "el código de criterio", cr.Codigo)
			}
			v.required(mpath+".descripcion", cr.Descripcion)
		}
	}
}

func (v *checker) esquema(path string, s Esquema, schemeCodes map[string]string) {
	if v.required(path+".codigo", s.Codigo) {
		v.unique(schemeCodes, path+".codigo", "el código de esquema", s.Codigo)
	}
	v.required(path+".nombre", s.Nombre)
	if len(s.Componentes) == 0 {
		v.addf(path+".componentes", "el esquema debe tener al menos un componente")
		return
	}
	codes := map[string]string{}
	var total int64
	for i, c := range s.Componentes {
		cpath := fmt.Sprintf("%s.componentes[%d]", path, i)
		if v.required(cpath+".codigo", c.Codigo) {
			v.unique(codes, cpath+".codigo", "el código de componente", c.Codigo)
		}
		v.required(cpath+".nombre", c.Nombre)
		if c.Peso <= 0 || c.Peso > 1 {
			v.addf(cpath+".peso", "%v debe ser mayor que 0 y como máximo 1 (0.40 es 40%%)", c.Peso)
		}
		if c.DescartarMasBajas < 0 {
			v.addf(cpath+".descartar_mas_bajas", "no puede ser negativo")
		}
		// Weights are numeric(9,6) and must sum to exactly 1 when published;
		// compare in millionths so 0.1+0.2+0.7 isn't lost to float error.
		total += int64(math.Round(c.Peso * 1e6))
	}
	if total != 1_000_000 {
		v.addf(path+".componentes", "los pesos suman %.6g y deben sumar exactamente 1", float64(total)/1e6)
	}
}

// ----------------------------------------------------------------- grados --

func (v *checker) grados(gs []Grado) map[string]Grado {
	known := map[string]Grado{}
	if len(gs) == 0 {
		v.addf("grados", "debe haber al menos un grado")
	}
	codes, ordenes := map[string]string{}, map[string]string{}
	for i, g := range gs {
		path := fmt.Sprintf("grados[%d]", i)
		if v.required(path+".codigo", g.Codigo) {
			v.unique(codes, path+".codigo", "el código de grado", g.Codigo)
			known[g.Codigo] = g
		}
		v.required(path+".etiqueta", g.Etiqueta)
		v.required(path+".nombre_largo", g.NombreLargo)
		if v.required(path+".nivel", g.Nivel) {
			v.oneOf(path+".nivel", g.Nivel, "inicial", "primaria", "secundaria", "otro")
		}
		if g.Orden < 1 {
			v.addf(path+".orden", "debe ser un número mayor que 0 (1ro de secundaria es 7)")
		} else {
			v.unique(ordenes, path+".orden", "el orden", fmt.Sprint(g.Orden))
		}
	}
	return known
}

// ------------------------------------------------------------------ aulas --

func (v *checker) aulas(as []Aula, grados map[string]Grado, docentes map[string]bool, anio AnioEscolar) map[string]Aula {
	known := map[string]Aula{}
	if len(as) == 0 {
		v.addf("aulas", "debe haber al menos un aula")
	}
	keys := map[string]string{}
	codes, siagies, docs := map[string]string{}, map[string]string{}, map[string]string{}
	anioInicio, _ := parseDate(anio.Inicio)
	anioFin, _ := parseDate(anio.Fin)
	for i, a := range as {
		path := fmt.Sprintf("aulas[%d]", i)
		okG := v.required(path+".grado", a.Grado)
		if okG {
			if _, ok := grados[a.Grado]; !ok {
				v.addf(path+".grado", "%q no está en la lista de grados", a.Grado)
			}
		}
		if v.required(path+".seccion", a.Seccion) && okG {
			v.unique(keys, path, "el aula", a.Key())
			known[a.Key()] = a
		}
		v.required(path+".nombre", a.Nombre)
		if v.optional(path+".tutor", a.Tutor) && !docentes[a.Tutor] {
			v.addf(path+".tutor", "%q no está en la lista de docentes", a.Tutor)
		}
		if a.Turno != "" {
			v.oneOf(path+".turno", a.Turno, "manana", "tarde", "noche", "completo")
		}
		if a.Capacidad < 0 {
			v.addf(path+".capacidad", "no puede ser negativa")
		}
		if a.Capacidad > 0 && len(a.Estudiantes) > a.Capacidad {
			v.addf(path+".estudiantes", "hay %d estudiantes y la capacidad del aula es %d", len(a.Estudiantes), a.Capacidad)
		}
		for j, e := range a.Estudiantes {
			v.estudiante(fmt.Sprintf("%s.estudiantes[%d]", path, j), e, codes, siagies, docs, anioInicio, anioFin)
		}
	}
	return known
}

func (v *checker) estudiante(path string, e Estudiante, codes, siagies, docs map[string]string, anioInicio, anioFin time.Time) {
	if v.required(path+".codigo", e.Codigo) {
		v.unique(codes, path+".codigo", "el código de estudiante", e.Codigo)
	}
	if v.optional(path+".codigo_siagie", e.CodigoSiagie) {
		if !reSiagie.MatchString(e.CodigoSiagie) {
			v.addf(path+".codigo_siagie", "%q debe tener exactamente 14 dígitos", e.CodigoSiagie)
		}
		v.unique(siagies, path+".codigo_siagie", "el código SIAGIE", e.CodigoSiagie)
	}
	v.required(path+".nombres", e.Nombres)
	v.required(path+".apellido_paterno", e.ApellidoPaterno)
	v.optional(path+".apellido_materno", e.ApellidoMaterno)
	v.optional(path+".nombre_preferido", e.NombrePreferido)
	v.optionalDate(path+".fecha_nacimiento", e.FechaNacimiento)
	if e.Sexo != "" {
		v.oneOf(path+".sexo", e.Sexo, "F", "M", "X", "unspecified")
	}
	hasType := v.optional(path+".tipo_documento", e.TipoDocumento)
	hasNum := v.optional(path+".numero_documento", e.NumeroDocumento)
	switch {
	case hasType != hasNum:
		v.addf(path, "tipo_documento y numero_documento van juntos: completa ambos o deja ambos vacíos")
	case hasType:
		v.oneOf(path+".tipo_documento", e.TipoDocumento, "DNI", "CE", "PAS", "PTP", "otro")
		if e.TipoDocumento == "DNI" && !reDNI.MatchString(e.NumeroDocumento) {
			v.addf(path+".numero_documento", "%q no es un DNI: debe tener 8 dígitos", e.NumeroDocumento)
		}
		v.unique(docs, path+".numero_documento", "el documento", e.TipoDocumento+" "+e.NumeroDocumento)
	}
	if d, ok := v.optionalDate(path+".fecha_matricula", e.FechaMatricula); ok && !anioInicio.IsZero() && !anioFin.IsZero() {
		if d.Before(anioInicio) || d.After(anioFin) {
			v.addf(path+".fecha_matricula", "%s está fuera del año escolar", e.FechaMatricula)
		}
	}
}

// ----------------------------------------------------------------- clases --

type slot struct {
	path, clase, aula, docente string
	dia, inicio, fin           int
}

func (v *checker) clases(cs []Clase, areas map[string]bool, aulas map[string]Aula, docentes map[string]bool, periodos []periodoRange) {
	if len(cs) == 0 {
		v.addf("clases", "debe haber al menos una clase")
	}
	nombres, codigos, pares := map[string]string{}, map[string]string{}, map[string]string{}
	horas := map[string]struct {
		path  string
		horas float64
	}{}
	var slots []slot
	for i, c := range cs {
		path := fmt.Sprintf("clases[%d]", i)
		// classes.name is NOT NULL and is what the teacher reads in "mis clases".
		if v.required(path+".nombre", c.Nombre) {
			v.unique(nombres, path+".nombre", "el nombre de clase", c.Nombre)
		}
		if v.required(path+".codigo", c.Codigo) {
			v.unique(codigos, path+".codigo", "el código de clase", c.Codigo)
		}
		okA := v.required(path+".area", c.Area)
		if okA && !areas[c.Area] {
			v.addf(path+".area", "%q no está en la lista de áreas", c.Area)
			okA = false
		}
		aula, okU := aulas[c.Aula]
		if v.required(path+".aula", c.Aula) && !okU {
			v.addf(path+".aula", "%q no existe; un aula se nombra grado-sección, por ejemplo \"1S-A\"", c.Aula)
		}
		if v.required(path+".docente", c.Docente) && !docentes[c.Docente] {
			v.addf(path+".docente", "%q no está en la lista de docentes", c.Docente)
		}
		// classes_course_section_key: one class per área per aula.
		if okA && okU {
			v.unique(pares, path, "la combinación área-aula", c.Area+" en "+c.Aula)
			// Classes of the same área and grado share one course, and
			// courses.weekly_hours is a single number.
			key := c.Area + "|" + aula.Grado
			if prev, seen := horas[key]; seen && prev.horas != c.HorasSemanales {
				v.addf(path+".horas_semanales", "%v no coincide con %v en %s: las clases de la misma área y grado comparten las horas semanales", c.HorasSemanales, prev.horas, prev.path)
			} else if !seen {
				horas[key] = struct {
					path  string
					horas float64
				}{path, c.HorasSemanales}
			}
		}
		if c.HorasSemanales < 0 {
			v.addf(path+".horas_semanales", "no puede ser negativo")
		}
		v.optional(path+".salon", c.Salon)

		if len(c.Horario) == 0 {
			v.addf(path+".horario", "la clase debe tener al menos una franja en el horario")
		}
		dias := map[int]bool{}
		for j, f := range c.Horario {
			fpath := fmt.Sprintf("%s.horario[%d]", path, j)
			dia, okD := 0, false
			if v.required(fpath+".dia", f.Dia) {
				if dia, okD = parseWeekday(f.Dia); !okD {
					v.addf(fpath+".dia", "%q no es un día; usa lunes, martes, miércoles, jueves, viernes, sábado o domingo", f.Dia)
				}
			}
			ini, okI := v.clock(fpath+".inicio", f.Inicio)
			fin, okF := v.clock(fpath+".fin", f.Fin)
			v.optional(fpath+".salon", f.Salon)
			if okI && okF && fin <= ini {
				v.addf(fpath+".fin", "debe ser posterior a la hora de inicio")
				continue
			}
			if okD && okI && okF {
				dias[dia] = true
				slots = append(slots, slot{fpath, path, c.Aula, c.Docente, dia, ini, fin})
			}
		}

		fechas := map[string]string{}
		for j, s := range c.Sesiones {
			spath := fmt.Sprintf("%s.sesiones[%d]", path, j)
			v.required(spath+".tema", s.Tema)
			d, ok := v.date(spath+".fecha", s.Fecha)
			if !ok {
				continue
			}
			v.unique(fechas, spath+".fecha", "la fecha de sesión", d.Format("2006-01-02"))
			if !inAnyPeriodo(d, periodos) {
				v.addf(spath+".fecha", "%s no cae dentro de ningún periodo del año escolar", s.Fecha)
			}
			if len(dias) > 0 && !dias[isoWeekday(d)] {
				v.addf(spath+".fecha", "%s es %s y la clase no tiene horario ese día; sus días son: %s", s.Fecha, weekdayNames[isoWeekday(d)], dayList(dias))
			}
		}
	}
	v.overlaps(slots)
}

// overlaps rejects two franjas at the same time for the same aula (the same
// students can't be in two classes) or for the same docente (double-booking).
// Overlap inside one class is left to the same check: a class is in one aula.
func (v *checker) overlaps(slots []slot) {
	for i := 0; i < len(slots); i++ {
		for j := i + 1; j < len(slots); j++ {
			a, b := slots[i], slots[j]
			if a.dia != b.dia || a.fin <= b.inicio || b.fin <= a.inicio {
				continue
			}
			switch {
			case a.aula == b.aula:
				v.addf(b.path, "se cruza con %s: el aula %s no puede tener dos clases a la vez", a.path, b.aula)
			case a.docente == b.docente:
				v.addf(b.path, "se cruza con %s: el docente %s no puede dictar dos clases a la vez", a.path, b.docente)
			}
		}
	}
}

func inAnyPeriodo(d time.Time, periodos []periodoRange) bool {
	for _, p := range periodos {
		if !d.Before(p.inicio) && !d.After(p.fin) {
			return true
		}
	}
	return false
}

// isoWeekday is Monday=1 .. Sunday=7, the numbering class_schedules uses.
func isoWeekday(d time.Time) int {
	if d.Weekday() == time.Sunday {
		return 7
	}
	return int(d.Weekday())
}

func dayList(dias map[int]bool) string {
	var ds []int
	for d := range dias {
		ds = append(ds, d)
	}
	sort.Ints(ds)
	names := make([]string, len(ds))
	for i, d := range ds {
		names[i] = weekdayNames[d]
	}
	return strings.Join(names, ", ")
}
