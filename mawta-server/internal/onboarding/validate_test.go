package onboarding

import (
	"os"
	"strings"
	"testing"

	"mawta-server/curriculum"
)

// catalog loads the embedded CNEB catalog once for the package's tests.
func catalog(t *testing.T) *curriculum.Catalog {
	t.Helper()
	cat, err := curriculum.Load()
	if err != nil {
		t.Fatalf("the embedded catalog must validate: %v", err)
	}
	return cat
}

// example loads the San Felipe example with its (deliberately empty)
// passwords filled in, so it validates.
func example(t *testing.T) *Spec {
	t.Helper()
	f, err := os.Open("../../seed/onboarding/ejemplo-san-felipe.json")
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	s, err := Decode(f)
	if err != nil {
		t.Fatalf("decode the example: %v", err)
	}
	for i := range s.Docentes {
		s.Docentes[i].Clave = "clave-de-prueba-" + s.Docentes[i].Usuario
	}
	return s
}

func errorsOf(t *testing.T, s *Spec) []string {
	t.Helper()
	err := ValidateWithCatalog(s, catalog(t))
	if err == nil {
		return nil
	}
	list, ok := err.(Errors)
	if !ok {
		t.Fatalf("Validate returned %T, want Errors", err)
	}
	return list
}

func TestExampleIsValid(t *testing.T) {
	if errs := errorsOf(t, example(t)); len(errs) > 0 {
		t.Fatalf("the example should validate once passwords are set:\n%s", strings.Join(errs, "\n"))
	}
}

// The example ships without passwords so a real one is never committed; it
// must refuse to load as-is rather than create accounts nobody can use.
func TestExampleWithoutPasswordsIsRejected(t *testing.T) {
	s := example(t)
	for i := range s.Docentes {
		s.Docentes[i].Clave = ""
	}
	errs := errorsOf(t, s)
	if len(errs) != 2 || !strings.Contains(errs[0], "docentes[0].clave: es obligatorio") {
		t.Fatalf("want one missing-clave error per docente, got:\n%s", strings.Join(errs, "\n"))
	}
}

// The blank template must never load: every <placeholder> is reported, all
// at once, each by its path.
func TestTemplateReportsEveryPlaceholder(t *testing.T) {
	f, err := os.Open("../../seed/onboarding/plantilla.json")
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	s, err := Decode(f)
	if err != nil {
		t.Fatalf("the template must at least be well-formed JSON: %v", err)
	}
	errs := errorsOf(t, s)
	for _, want := range []string{
		"colegio.nombre: falta completar",
		"colegio.codigo_modular: falta completar",
		"docentes[0].clave: falta completar",
		"areas[0].codigo: falta completar",
		"grados[0].grado_cneb: falta completar",
		"clases[0].horario[0].dia: falta completar",
		"clases[0].sesiones[0].tema: falta completar",
	} {
		if !containsPrefix(errs, want) {
			t.Errorf("missing %q in:\n%s", want, strings.Join(errs, "\n"))
		}
	}
}

func TestDecodeRejectsUnknownKeys(t *testing.T) {
	_, err := Decode(strings.NewReader(`{"colegio": {"nombrre": "x"}}`))
	if err == nil || !strings.Contains(err.Error(), "nombrre") {
		t.Fatalf("a misspelled key must be an error naming it, got %v", err)
	}
}

func TestDecodeReportsTheLineOfASyntaxError(t *testing.T) {
	_, err := Decode(strings.NewReader("{\n  \"colegio\": {\n    \"nombre\": \"x\",\n  }\n}"))
	if err == nil || !strings.Contains(err.Error(), "línea 4") {
		t.Fatalf("want the line of the trailing comma, got %v", err)
	}
}

func TestValidationRules(t *testing.T) {
	cases := []struct {
		name   string
		mutate func(s *Spec)
		want   string
	}{
		{"modular code shape", func(s *Spec) { s.Colegio.CodigoModular = "123" },
			"colegio.codigo_modular: \"123\" debe tener exactamente 7 dígitos"},
		{"unknown enum", func(s *Spec) { s.Colegio.Tipo = "estatal" },
			"colegio.tipo: \"estatal\" no es válido"},
		{"bad time zone", func(s *Spec) { s.Colegio.ZonaHoraria = "Lima" },
			"colegio.zona_horaria: \"Lima\" no es una zona horaria IANA"},
		{"no periodos", func(s *Spec) { s.AnioEscolar.Periodos = nil },
			"anio_escolar.periodos: debe haber al menos un periodo"},
		{"too many periodos for the structure", func(s *Spec) { s.AnioEscolar.Estructura = "semestre" },
			"anio_escolar.periodos[2].numero: 3 no es válido"},
		{"periodos sharing a boundary day", func(s *Spec) { s.AnioEscolar.Periodos[1].Inicio = "2026-05-29" },
			"anio_escolar.periodos[1]: se superpone con anio_escolar.periodos[0]"},
		{"periodo outside the year", func(s *Spec) { s.AnioEscolar.Periodos[2].Fin = "2026-12-30" },
			"anio_escolar.periodos[2]: del 2026-08-31 al 2026-12-30 se sale del año escolar"},
		{"bad date format", func(s *Spec) { s.AnioEscolar.Inicio = "02/03/2026" },
			"anio_escolar.inicio: \"02/03/2026\" no es una fecha válida"},
		{"uppercase username", func(s *Spec) { s.Docentes[0].Usuario = "Jeffrey" },
			"docentes[0].usuario: \"Jeffrey\" solo puede tener minúsculas"},
		{"short password", func(s *Spec) { s.Docentes[0].Clave = "corta" },
			"docentes[0].clave: debe tener entre 10 y 72 caracteres"},
		{"duplicate email", func(s *Spec) { s.Docentes[1].Email = "AmaruOrihuela@gmail.com" },
			"docentes[1].email: el correo \"amaruorihuela@gmail.com\" está repetido"},
		{"area not in the catalog", func(s *Spec) { s.Areas[1].Codigo = "COM" },
			"areas[1].codigo: \"COM\" no es un área del catálogo CNEB"},
		{"transversal not in the catalog", func(s *Spec) { s.CompetenciasTransversales[0] = "TR-C9" },
			"competencias_transversales[0]: \"TR-C9\" no es una competencia transversal del catálogo CNEB"},
		{"repeated transversal", func(s *Spec) { s.CompetenciasTransversales[1] = "TR-C1" },
			"competencias_transversales[1]: la competencia transversal \"TR-C1\" está repetido"},
		{"legacy criterion pointing at an unknown capability", func(s *Spec) { s.Areas[0].CriteriosLegacy[0].Capacidad = "MAT-C1-CAP9" },
			"areas[0].criterios_legacy[0].capacidad: \"MAT-C1-CAP9\" no es una capacidad del área MAT"},
		{"legacy criterion pointing at another area's capability", func(s *Spec) { s.Areas[0].CriteriosLegacy[0].Capacidad = "CCSS-C1-CAP1" },
			"areas[0].criterios_legacy[0].capacidad: \"CCSS-C1-CAP1\" no es una capacidad del área MAT"},
		{"duplicate legacy criterion code", func(s *Spec) { s.Areas[0].CriteriosLegacy[1].Codigo = "MAT-C1-CR1" },
			"areas[0].criterios_legacy[1].codigo: el código de criterio \"MAT-C1-CR1\" está repetido"},
		{"grado_cneb not in the catalog", func(s *Spec) { s.Grados[0].GradoCNEB = "9S" },
			"grados[0].grado_cneb: \"9S\" no es un grado del catálogo CNEB"},
		{"missing grado_cneb", func(s *Spec) { s.Grados[0].GradoCNEB = "" },
			"grados[0].grado_cneb: es obligatorio"},
		{"weights not summing to 1", func(s *Spec) { s.Areas[0].EsquemaCalificacion.Componentes[2].Peso = 0.25 },
			"areas[0].esquema_calificacion.componentes: los pesos suman 1.05"},
		{"aula of an unknown grado", func(s *Spec) { s.Aulas[0].Grado = "2S" },
			"aulas[0].grado: \"2S\" no está en la lista de grados"},
		{"tutor who is not a docente", func(s *Spec) { s.Aulas[0].Tutor = "maria" },
			"aulas[0].tutor: \"maria\" no está en la lista de docentes"},
		{"siagie shape", func(s *Spec) { s.Aulas[0].Estudiantes[0].CodigoSiagie = "123" },
			"aulas[0].estudiantes[0].codigo_siagie: \"123\" debe tener exactamente 14 dígitos"},
		{"document without number", func(s *Spec) { s.Aulas[0].Estudiantes[0].NumeroDocumento = "" },
			"aulas[0].estudiantes[0]: tipo_documento y numero_documento van juntos"},
		{"dni shape", func(s *Spec) { s.Aulas[0].Estudiantes[0].NumeroDocumento = "1234" },
			"aulas[0].estudiantes[0].numero_documento: \"1234\" no es un DNI"},
		{"duplicate student code", func(s *Spec) { s.Aulas[0].Estudiantes[1].Codigo = "EST-DEMO-2026-01" },
			"aulas[0].estudiantes[1].codigo: el código de estudiante \"EST-DEMO-2026-01\" está repetido"},
		{"class without a name", func(s *Spec) { s.Clases[0].Nombre = "" },
			"clases[0].nombre: es obligatorio"},
		{"class in an unknown aula", func(s *Spec) { s.Clases[0].Aula = "1S-B" },
			"clases[0].aula: \"1S-B\" no existe"},
		{"two classes of one área in one aula", func(s *Spec) { s.Clases[1].Area = "MAT" },
			"clases[1]: la combinación área-aula \"MAT en 1S-A\" está repetido"},
		{"class without horario", func(s *Spec) { s.Clases[0].Horario = nil },
			"clases[0].horario: la clase debe tener al menos una franja"},
		{"bad weekday", func(s *Spec) { s.Clases[0].Horario[0].Dia = "lunes." },
			"clases[0].horario[0].dia: \"lunes.\" no es un día"},
		{"end before start", func(s *Spec) { s.Clases[0].Horario[0].Fin = "07:00" },
			"clases[0].horario[0].fin: debe ser posterior a la hora de inicio"},
		{"aula double-booked", func(s *Spec) { s.Clases[1].Horario[0] = Franja{Dia: "lunes", Inicio: "09:00", Fin: "10:00"} },
			"clases[1].horario[0]: se cruza con clases[0].horario[0]: el aula 1S-A no puede tener dos clases a la vez"},
		{"sesión on a day without horario", func(s *Spec) { s.Clases[0].Sesiones[0].Fecha = "2026-03-03" },
			"clases[0].sesiones[0].fecha: 2026-03-03 es martes y la clase no tiene horario ese día; sus días son: lunes, miércoles, viernes"},
		{"sesión outside every periodo", func(s *Spec) { s.Clases[0].Sesiones[0].Fecha = "2026-05-29" },
			""},
		{"sesión in the winter break", func(s *Spec) { s.Clases[0].Sesiones[0].Fecha = "2026-12-21" },
			"clases[0].sesiones[0].fecha: 2026-12-21 no cae dentro de ningún periodo"},
		{"two temas for one date", func(s *Spec) { s.Clases[0].Sesiones[1].Fecha = "2026-03-02" },
			"clases[0].sesiones[1].fecha: la fecha de sesión \"2026-03-02\" está repetido"},
		{"leftover placeholder", func(s *Spec) { s.Clases[0].Sesiones[0].Tema = "<nombre de la sesión>" },
			"clases[0].sesiones[0].tema: falta completar"},
		{"sesión on a día no lectivo", func(s *Spec) { s.Clases[0].Sesiones[3].Fecha = "2026-06-29" },
			"clases[0].sesiones[3].fecha: 2026-06-29 es un día no lectivo (anio_escolar.dias_no_lectivos[3])"},
		{"día no lectivo outside the year", func(s *Spec) { s.AnioEscolar.DiasNoLectivos[0].Fecha = "2026-01-01" },
			"anio_escolar.dias_no_lectivos[0]: del 2026-01-01 al 2026-01-01 se sale del año escolar"},
		{"día no lectivo of an unknown tipo", func(s *Spec) { s.AnioEscolar.DiasNoLectivos[0].Tipo = "fiesta" },
			"anio_escolar.dias_no_lectivos[0].tipo: \"fiesta\" no es válido"},
		{"día no lectivo range ending before it starts", func(s *Spec) { s.AnioEscolar.DiasNoLectivos[5].Hasta = "2026-07-20" },
			"anio_escolar.dias_no_lectivos[5].hasta: 2026-07-20 es anterior a desde"},
		{"día no lectivo with fecha and a range", func(s *Spec) { s.AnioEscolar.DiasNoLectivos[0].Desde = "2026-04-01" },
			"anio_escolar.dias_no_lectivos[0]: usa fecha (un día) o desde y hasta"},
		{"día no lectivo without a date", func(s *Spec) { s.AnioEscolar.DiasNoLectivos[0].Fecha = "" },
			"anio_escolar.dias_no_lectivos[0]: falta fecha"},
		{"día no lectivo declared twice", func(s *Spec) { s.AnioEscolar.DiasNoLectivos[4].Fecha = "2026-07-28" },
			"anio_escolar.dias_no_lectivos[5]: el día 2026-07-28 ya está en anio_escolar.dias_no_lectivos[4]"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			s := example(t)
			tc.mutate(s)
			errs := errorsOf(t, s)
			if tc.want == "" {
				if len(errs) > 0 {
					t.Fatalf("want no error, got:\n%s", strings.Join(errs, "\n"))
				}
				return
			}
			if !containsPrefix(errs, tc.want) {
				t.Fatalf("want an error starting %q, got:\n%s", tc.want, strings.Join(errs, "\n"))
			}
		})
	}
}

func containsPrefix(errs []string, want string) bool {
	for _, e := range errs {
		if strings.HasPrefix(e, want) {
			return true
		}
	}
	return false
}
