// Package onboarding loads a whole school — colegio, año escolar, docentes,
// áreas con su árbol CNEB, aulas con estudiantes, clases, horario y las
// sesiones que ese horario produce — from one JSON file filled in by the
// onboarding team. See docs/instalar-un-colegio.md for the file format.
//
// The curriculum tree (competencias, capacidades, estándares, desempeños) is
// no longer typed in the file: each área names a catalog area by codigo and
// the loader copies the tree from the embedded CNEB catalog
// (mawta-server/curriculum). What the school decides is which áreas, grados
// and transversales it uses.
package onboarding

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
)

// Spec is the onboarding file. Keys are in Spanish because the people filling
// it in are; entries point at each other by code (area "MAT", aula "1S-A",
// docente "jeffrey"), never by id.
type Spec struct {
	Colegio                   Colegio     `json:"colegio"`
	AnioEscolar               AnioEscolar `json:"anio_escolar"`
	Docentes                  []Docente   `json:"docentes"`
	Areas                     []Area      `json:"areas"`
	CompetenciasTransversales []string    `json:"competencias_transversales"`
	Grados                    []Grado     `json:"grados"`
	Aulas                     []Aula      `json:"aulas"`
	Clases                    []Clase     `json:"clases"`
}

type Colegio struct {
	Nombre        string `json:"nombre"`
	RazonSocial   string `json:"razon_social"`
	CodigoModular string `json:"codigo_modular"`
	Tipo          string `json:"tipo"`
	Ciudad        string `json:"ciudad"`
	Region        string `json:"region"`
	ZonaHoraria   string `json:"zona_horaria"`
}

type AnioEscolar struct {
	Anio           int            `json:"anio"`
	Nombre         string         `json:"nombre"`
	Inicio         string         `json:"inicio"`
	Fin            string         `json:"fin"`
	Estructura     string         `json:"estructura"`
	Periodos       []Periodo      `json:"periodos"`
	DiasNoLectivos []DiaNoLectivo `json:"dias_no_lectivos"`
}

// DiaNoLectivo is a day, or an inclusive range of days, without class:
// feriados, vacaciones and días de gestión. Either Fecha is set (one day) or
// Desde and Hasta are (a range). The loader writes one non_teaching_days row
// per day, and no class_sessions are generated on those days.
type DiaNoLectivo struct {
	Fecha  string `json:"fecha"`
	Desde  string `json:"desde"`
	Hasta  string `json:"hasta"`
	Tipo   string `json:"tipo"` // feriado | vacaciones | gestion
	Nombre string `json:"nombre"`
}

type Periodo struct {
	Numero            int    `json:"numero"`
	Nombre            string `json:"nombre"`
	Abreviatura       string `json:"abreviatura"`
	Inicio            string `json:"inicio"`
	Fin               string `json:"fin"`
	FechaEntregaNotas string `json:"fecha_entrega_notas"`
}

type Docente struct {
	Usuario        string `json:"usuario"`
	Clave          string `json:"clave"`
	Email          string `json:"email"`
	Nombres        string `json:"nombres"`
	Apellidos      string `json:"apellidos"`
	NombreVisible  string `json:"nombre_visible"`
	Cargo          string `json:"cargo"`
	CodigoEmpleado string `json:"codigo_empleado"`
	FechaIngreso   string `json:"fecha_ingreso"`
}

// Area names a catalog area by codigo; the loader copies that area's
// competencies, capabilities, standards and the performances of the school's
// grades from the catalog. Nombre and Icono stay in the
// file because they are school decisions, not curriculum.
type Area struct {
	Codigo          string           `json:"codigo"` // catalog area code, e.g. MAT
	Nombre          string           `json:"nombre"` // how the school names the subject
	Icono           string           `json:"icono"`
	EsTutoria       bool             `json:"es_tutoria"`
	CriteriosLegacy []CriterioLegacy `json:"criterios_legacy"` // optional, see CriterioLegacy
}

// CriterioLegacy is an evaluation criterion the school already uses, kept so
// seed/seed_demo.sql and existing schools keep working. It points at a
// capability by code (the catalog derives capability codes as
// <competency code>-CAP<numero>), because a criterion must hang off a
// capability (evaluation_criteria.capability_id).
type CriterioLegacy struct {
	Codigo      string `json:"codigo"`
	Descripcion string `json:"descripcion"`
	Capacidad   string `json:"capacidad"` // capability code, e.g. MAT-C1-CAP1
}

// Grado is a grade as the school names it. GradoCNEB names the catalog grade
// (e.g. "1S"), which sets grade_levels.stage and grade_levels.cycle and
// selects which performances the loader copies.
type Grado struct {
	Codigo      string `json:"codigo"`
	Etiqueta    string `json:"etiqueta"`
	NombreLargo string `json:"nombre_largo"`
	Nivel       string `json:"nivel"`
	Orden       int    `json:"orden"`
	GradoCNEB   string `json:"grado_cneb"`
}

type Aula struct {
	Grado       string       `json:"grado"`
	Seccion     string       `json:"seccion"`
	Nombre      string       `json:"nombre"`
	Tutor       string       `json:"tutor"`
	Turno       string       `json:"turno"`
	Capacidad   int          `json:"capacidad"`
	Estudiantes []Estudiante `json:"estudiantes"`
}

// Key is how a clase points at its aula: grado and sección joined, "1S-A".
func (a Aula) Key() string { return a.Grado + "-" + a.Seccion }

type Estudiante struct {
	Codigo          string `json:"codigo"`
	CodigoSiagie    string `json:"codigo_siagie"`
	Nombres         string `json:"nombres"`
	ApellidoPaterno string `json:"apellido_paterno"`
	ApellidoMaterno string `json:"apellido_materno"`
	NombrePreferido string `json:"nombre_preferido"`
	FechaNacimiento string `json:"fecha_nacimiento"`
	Sexo            string `json:"sexo"`
	TipoDocumento   string `json:"tipo_documento"`
	NumeroDocumento string `json:"numero_documento"`
	FechaMatricula  string `json:"fecha_matricula"`
	ApoyoInclusion  bool   `json:"apoyo_inclusion"`
}

type Clase struct {
	Nombre         string   `json:"nombre"`
	Codigo         string   `json:"codigo"`
	Area           string   `json:"area"`
	Aula           string   `json:"aula"`
	Docente        string   `json:"docente"`
	HorasSemanales float64  `json:"horas_semanales"`
	Salon          string   `json:"salon"`
	Horario        []Franja `json:"horario"`
	Sesiones       []Sesion `json:"sesiones"`
}

type Franja struct {
	Dia    string `json:"dia"`
	Inicio string `json:"inicio"`
	Fin    string `json:"fin"`
	Salon  string `json:"salon"`
}

type Sesion struct {
	Fecha string `json:"fecha"`
	Tema  string `json:"tema"`
}

// Decode reads one onboarding file. An unknown key is an error rather than
// being ignored: a misspelled "apellido_paterrno" would otherwise load a
// student with no surname and nobody would notice until the report card.
func Decode(r io.Reader) (*Spec, error) {
	raw, err := io.ReadAll(r)
	if err != nil {
		return nil, fmt.Errorf("leer el archivo: %w", err)
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	var s Spec
	if err := dec.Decode(&s); err != nil {
		return nil, describeDecodeError(raw, err)
	}
	if dec.More() {
		return nil, errors.New("el archivo tiene contenido después del objeto JSON principal")
	}
	return &s, nil
}

func describeDecodeError(raw []byte, err error) error {
	var syntax *json.SyntaxError
	var typ *json.UnmarshalTypeError
	switch {
	case errors.As(err, &syntax):
		return fmt.Errorf("JSON mal formado en la línea %d: %s (revisa comas, comillas y llaves)", lineOf(raw, syntax.Offset), syntax.Error())
	case errors.As(err, &typ):
		return fmt.Errorf("línea %d: el campo %q espera un valor de tipo %s, no %s", lineOf(raw, typ.Offset), typ.Field, typ.Type, typ.Value)
	default:
		return fmt.Errorf("JSON inválido: %w", err)
	}
}

func lineOf(raw []byte, offset int64) int {
	if offset > int64(len(raw)) {
		offset = int64(len(raw))
	}
	return bytes.Count(raw[:offset], []byte("\n")) + 1
}
