// Package curriculum embeds the national curriculum (CNEB) catalog that every
// school loads from: the grades with their cycles, the (modality, cycle) →
// expected-standard-level mapping, the areas with their school-facing
// competency codes, and one file per CNEB competency holding its capacities,
// learning standards and grade-level performances.
//
// The data under cneb/ is official text transcribed from RM 281-2016 and
// RM 649-2016. Nothing in this package writes, completes or paraphrases it:
// the loader stores it verbatim and validation only checks consistency. A
// competency is stored once because the same CNEB competency belongs to
// different areas depending on the level; areas only reference competencies.
package curriculum

import (
	"bytes"
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"regexp"
	"strconv"
	"strings"
)

// The catalog lives as data next to this file (go:embed cannot reach outside
// the package directory, and the data must not move). Only *.json is embedded:
// anything else in cneb/ is ignored.
//
//go:embed cneb/*.json cneb/competencias/*.json
var files embed.FS

const (
	cnebPath        = "cneb/cneb.json"
	areasPath       = "cneb/areas.json"
	competenciasDir = "cneb/competencias"
	// DefaultModality is the modality the shipped catalog maps levels for.
	// The onboarding file may name another one later; the mapping table is
	// the only source of the correspondence.
	DefaultModality = "ebr"
)

// Load decodes and validates the embedded catalog. Call it once at startup and
// fail fast: a binary carrying a broken catalog must refuse to load any
// school, not install one against half a curriculum.
func Load() (*Catalog, error) { return loadFS(files) }

// CNEB is the shape of cneb/cneb.json: the source note, the grades in order,
// and the (modality, cycle) → expected level mapping.
type CNEB struct {
	Fuente           string          `json:"fuente"`
	Grados           []Grade         `json:"grados"`
	NivelesEsperados []NivelEsperado `json:"niveles_esperados"`
}

// Grade is one CNEB grade: its code ("1S"), its education level and its cycle.
type Grade struct {
	Codigo string `json:"codigo"`
	Nivel  string `json:"nivel"`
	Ciclo  string `json:"ciclo"`
}

// NivelEsperado says which learning-standard level (1-8) a cycle of a
// modality ends at.
type NivelEsperado struct {
	Modalidad string `json:"modalidad"`
	Ciclo     string `json:"ciclo"`
	Nivel     int    `json:"nivel"`
}

// Areas is the shape of cneb/areas.json.
type Areas struct {
	Areas         []Area        `json:"areas"`
	Transversales []Transversal `json:"transversales"`
}

// Area is one curricular area of the programmes: the school-facing code and
// the competencies it holds, each named by its CNEB number.
type Area struct {
	Codigo       string            `json:"codigo"`
	Nombre       string            `json:"nombre"`
	Niveles      []string          `json:"niveles"`
	Competencias []AreaCompetencia `json:"competencias"`
}

// AreaCompetencia is a competency an area teaches, under the code schools use.
type AreaCompetencia struct {
	Codigo     string `json:"codigo"`
	NumeroCNEB int    `json:"numero_cneb"`
}

// Transversal is one of the cross-curricular competencies: it belongs to no
// area and has no grade-level performances (they are per cycle, deferred).
type Transversal struct {
	Codigo     string `json:"codigo"`
	NumeroCNEB int    `json:"numero_cneb"`
}

// Competencia is one CNEB competency with its capacities, its learning
// standards (levels 1-8) and its grade-level performances.
type Competencia struct {
	NumeroCNEB  int         `json:"numero_cneb"`
	Nombre      string      `json:"nombre"`
	Capacidades []Capacidad `json:"capacidades"`
	Estandares  []Estandar  `json:"estandares"`
	Desempenos  []Desempeno `json:"desempenos"`
}

// Capacidad is one capacity of a competency, in programme order.
type Capacidad struct {
	Numero int    `json:"numero"`
	Nombre string `json:"nombre"`
}

// Estandar is one learning standard of a competency, by level (1-8).
type Estandar struct {
	Nivel int    `json:"nivel"`
	Texto string `json:"texto"`
}

// Desempeno is one grade-level performance. CapacidadSugerida is a hint
// inferred when the data was transcribed, never official: it is nil when the
// data file does not set it, and the loader stores it only then.
type Desempeno struct {
	Grado             string `json:"grado"`
	Orden             int    `json:"orden"`
	Texto             string `json:"texto"`
	CapacidadSugerida *int   `json:"capacidad_sugerida"`
}

// Catalog is the decoded, validated CNEB catalog, with the lookups the
// onboarding loader and the sync need.
type Catalog struct {
	Fuente           string
	Grados           []Grade
	Grado            map[string]Grade
	NivelesEsperados []NivelEsperado
	Areas            []Area
	Area             map[string]Area
	Transversales    []Transversal
	Transversal      map[string]Transversal
	Competencias     map[int]Competencia
	// NumeroByCode maps a school-facing competency code ("MAT-C1", "TR-C1")
	// to its CNEB number.
	NumeroByCode map[string]int
	// CapabilityCodesByArea maps an area code to every capability code its
	// competencies define, so an onboarding file can be checked against it.
	CapabilityCodesByArea map[string]map[string]bool
}

// CapabilityCode derives a capability's code from its competency's code and
// the capability's programme number: MAT-C1 + 1 → MAT-C1-CAP1. The
// convention is the one schools and seed/seed_demo.sql already use, so the
// md5-derived ids in internal/onboarding/ids.go do not change.
func CapabilityCode(competencyCode string, numero int) string {
	return fmt.Sprintf("%s-CAP%d", competencyCode, numero)
}

// CompetenciaByCode returns the competency a school-facing code names.
func (c *Catalog) CompetenciaByCode(code string) (Competencia, bool) {
	n, ok := c.NumeroByCode[code]
	if !ok {
		return Competencia{}, false
	}
	comp, ok := c.Competencias[n]
	return comp, ok
}

// ExpectedLevel returns the learning-standard level a cycle of a modality ends
// at, the only source of that correspondence.
func (c *Catalog) ExpectedLevel(modality, ciclo string) (int, bool) {
	for _, n := range c.NivelesEsperados {
		if n.Modalidad == modality && n.Ciclo == ciclo {
			return n.Nivel, true
		}
	}
	return 0, false
}

// LastGradeOfCycle returns the last grade of a cycle in catalog order: the
// grade whose programme describes reaching the cycle's standard.
func (c *Catalog) LastGradeOfCycle(ciclo string) (string, bool) {
	last := ""
	for _, g := range c.Grados {
		if g.Ciclo == ciclo {
			last = g.Codigo
		}
	}
	return last, last != ""
}

// EnProceso reports whether a grade's performances are "in progress towards"
// the cycle standard (true) rather than "reaching" it (false): only the last
// grade of a cycle reaches it. An unknown grade reports false; validation
// rejects it before this is consulted.
func (c *Catalog) EnProceso(grado string) bool {
	g, ok := c.Grado[grado]
	if !ok {
		return false
	}
	last, ok := c.LastGradeOfCycle(g.Ciclo)
	if !ok {
		return false
	}
	return grado != last
}

// Errors is every problem found in the catalog data, one line each, so the
// whole catalog is fixed in one pass.
type Errors []string

func (e Errors) Error() string {
	return "el catálogo CNEB tiene " + strconv.Itoa(len(e)) + " problema(s):\n  - " +
		strings.Join(e, "\n  - ")
}

// loadFS reads the catalog from fsys. Load passes the embedded files; tests
// pass a synthetic filesystem to exercise the validation errors.
func loadFS(fsys fs.FS) (*Catalog, error) {
	var doc CNEB
	if err := decodeStrict(fsys, cnebPath, &doc); err != nil {
		return nil, err
	}
	var areasDoc Areas
	if err := decodeStrict(fsys, areasPath, &areasDoc); err != nil {
		return nil, err
	}

	c := &Catalog{
		Fuente:                doc.Fuente,
		Grados:                doc.Grados,
		Grado:                 map[string]Grade{},
		NivelesEsperados:      doc.NivelesEsperados,
		Areas:                 areasDoc.Areas,
		Area:                  map[string]Area{},
		Transversales:         areasDoc.Transversales,
		Transversal:           map[string]Transversal{},
		Competencias:          map[int]Competencia{},
		NumeroByCode:          map[string]int{},
		CapabilityCodesByArea: map[string]map[string]bool{},
	}
	var errs Errors

	errs = append(errs, c.checkGrades(doc)...)
	errs = append(errs, c.checkCompetencias(fsys)...)
	errs = append(errs, c.checkAreas(areasDoc)...)

	if len(errs) > 0 {
		return nil, errs
	}
	if c.Fuente == "" {
		return nil, Errors{cnebPath + ".fuente: es obligatorio (nombra la RM 281-2016 y la RM 649-2016)"}
	}
	return c, nil
}

// checkGrades validates cneb.json: unique grade codes, valid levels and
// cycles, a unique (modality, cycle) → level mapping, and a level for every
// cycle a grade uses.
func (c *Catalog) checkGrades(doc CNEB) Errors {
	var errs Errors
	if len(doc.Grados) == 0 {
		errs = append(errs, cnebPath+".grados: debe haber al menos un grado")
	}
	seen := map[string]string{}
	var ciclos []string
	inCiclos := map[string]bool{}
	for i, g := range doc.Grados {
		path := fmt.Sprintf("%s.grados[%d]", cnebPath, i)
		if g.Codigo == "" {
			errs = append(errs, path+".codigo: es obligatorio")
			continue
		}
		if first, dup := seen[g.Codigo]; dup {
			errs = append(errs, fmt.Sprintf("%s.codigo: el grado %q está repetido (ya aparece en %s)", path, g.Codigo, first))
			continue
		}
		seen[g.Codigo] = path
		if !validNivel(g.Nivel) {
			errs = append(errs, fmt.Sprintf("%s.nivel: %q no es un nivel válido; usa inicial, primaria o secundaria", path, g.Nivel))
		}
		if !validCiclo(g.Ciclo) {
			errs = append(errs, fmt.Sprintf("%s.ciclo: %q no es un ciclo válido; usa ciclo_i a ciclo_vii", path, g.Ciclo))
		} else if !inCiclos[g.Ciclo] {
			inCiclos[g.Ciclo] = true
			ciclos = append(ciclos, g.Ciclo)
		}
		c.Grado[g.Codigo] = g
	}

	seenLevel := map[string]string{}
	for i, n := range doc.NivelesEsperados {
		path := fmt.Sprintf("%s.niveles_esperados[%d]", cnebPath, i)
		if n.Modalidad == "" {
			errs = append(errs, path+".modalidad: es obligatoria")
		}
		if !validCiclo(n.Ciclo) {
			errs = append(errs, fmt.Sprintf("%s.ciclo: %q no es un ciclo válido; usa ciclo_i a ciclo_vii", path, n.Ciclo))
		}
		if n.Nivel < 1 || n.Nivel > 8 {
			errs = append(errs, fmt.Sprintf("%s.nivel: %d no está entre 1 y 8", path, n.Nivel))
		}
		key := n.Modalidad + "|" + n.Ciclo
		if first, dup := seenLevel[key]; dup {
			errs = append(errs, fmt.Sprintf("%s: la combinación modalidad %q y ciclo %q está repetida (ya aparece en %s)", path, n.Modalidad, n.Ciclo, first))
		} else {
			seenLevel[key] = path
		}
	}
	for _, ciclo := range ciclos {
		found := false
		for _, n := range doc.NivelesEsperados {
			if n.Ciclo == ciclo {
				found = true
				break
			}
		}
		if !found {
			errs = append(errs, fmt.Sprintf("%s.niveles_esperados: falta el ciclo %q (lo usa el grado %s)", cnebPath, ciclo, c.firstGradeOf(ciclo)))
		}
	}
	return errs
}

func (c *Catalog) firstGradeOf(ciclo string) string {
	for _, g := range c.Grados {
		if g.Ciclo == ciclo {
			return g.Codigo
		}
	}
	return ""
}

// checkCompetencias decodes and validates every competency file: the file
// name must match the CNEB number, capacities must exist and be unique,
// standard levels must be 1-8 and unique, performances must name a catalog
// grade with a unique order, and a suggested capacity must belong to the same
// competency.
func (c *Catalog) checkCompetencias(fsys fs.FS) Errors {
	var errs Errors
	entries, err := fs.ReadDir(fsys, competenciasDir)
	if err != nil {
		return Errors{fmt.Sprintf("leer %s: %s", competenciasDir, err)}
	}
	seenNumero := map[int]string{}
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		name := competenciasDir + "/" + e.Name()
		var comp Competencia
		if err := decodeStrict(fsys, name, &comp); err != nil {
			errs = append(errs, err.Error())
			continue
		}
		errs = append(errs, c.checkCompetencia(name, e.Name(), comp)...)
		if comp.NumeroCNEB <= 0 {
			continue
		}
		if first, dup := seenNumero[comp.NumeroCNEB]; dup {
			errs = append(errs, fmt.Sprintf("%s.numero_cneb: la competencia %d está repetida (ya aparece en %s)", name, comp.NumeroCNEB, first))
			continue
		}
		seenNumero[comp.NumeroCNEB] = name
		c.Competencias[comp.NumeroCNEB] = comp
	}
	return errs
}

func (c *Catalog) checkCompetencia(name, fileName string, comp Competencia) Errors {
	var errs Errors
	if comp.NumeroCNEB <= 0 {
		errs = append(errs, name+".numero_cneb: debe ser el número de la competencia en el CNEB, mayor que 0")
	} else if want := competenciaFile(comp.NumeroCNEB); fileName != want {
		errs = append(errs, fmt.Sprintf("%s.numero_cneb: el archivo se llama %q pero la competencia dice ser la número %d; renómbralo a %q o corrige el número", name, fileName, comp.NumeroCNEB, want))
	}
	if comp.Nombre == "" {
		errs = append(errs, name+".nombre: es obligatorio")
	}
	if len(comp.Capacidades) == 0 {
		errs = append(errs, name+".capacidades: la competencia debe tener al menos una capacidad")
	}
	seenCap := map[int]string{}
	for i, cap := range comp.Capacidades {
		path := fmt.Sprintf("%s.capacidades[%d]", name, i)
		if cap.Numero < 1 {
			errs = append(errs, path+".numero: debe ser mayor que 0")
			continue
		}
		if first, dup := seenCap[cap.Numero]; dup {
			errs = append(errs, fmt.Sprintf("%s.numero: la capacidad %d está repetida (ya aparece en %s)", path, cap.Numero, first))
			continue
		}
		seenCap[cap.Numero] = path
		if cap.Nombre == "" {
			errs = append(errs, path+".nombre: es obligatorio")
		}
	}
	seenLevel := map[int]string{}
	for i, e := range comp.Estandares {
		path := fmt.Sprintf("%s.estandares[%d]", name, i)
		if e.Nivel < 1 || e.Nivel > 8 {
			errs = append(errs, fmt.Sprintf("%s.nivel: %d no está entre 1 y 8", path, e.Nivel))
			continue
		}
		if first, dup := seenLevel[e.Nivel]; dup {
			errs = append(errs, fmt.Sprintf("%s.nivel: el nivel %d está repetido (ya aparece en %s)", path, e.Nivel, first))
			continue
		}
		seenLevel[e.Nivel] = path
		if e.Texto == "" {
			errs = append(errs, path+".texto: es obligatorio")
		}
	}
	seenOrden := map[string]string{}
	for i, d := range comp.Desempenos {
		path := fmt.Sprintf("%s.desempenos[%d]", name, i)
		if _, ok := c.Grado[d.Grado]; !ok {
			errs = append(errs, fmt.Sprintf("%s.grado: %q no es un grado del catálogo; los grados de cneb.json son: %s", path, d.Grado, c.gradeList()))
		}
		if d.Orden < 1 {
			errs = append(errs, path+".orden: debe ser mayor que 0")
		} else {
			key := d.Grado + "|" + strconv.Itoa(d.Orden)
			if first, dup := seenOrden[key]; dup {
				errs = append(errs, fmt.Sprintf("%s.orden: el orden %d del grado %q está repetido (ya aparece en %s)", path, d.Orden, d.Grado, first))
				continue
			}
			seenOrden[key] = path
		}
		if d.Texto == "" {
			errs = append(errs, path+".texto: es obligatorio")
		}
		if d.CapacidadSugerida != nil {
			if _, ok := seenCap[*d.CapacidadSugerida]; !ok {
				errs = append(errs, fmt.Sprintf("%s.capacidad_sugerida: %d no es una capacidad de la competencia %d", path, *d.CapacidadSugerida, comp.NumeroCNEB))
			}
		}
	}
	return errs
}

// checkAreas validates areas.json: unique area and transversal codes,
// competency codes unique across the whole catalog (the same CNEB competency
// gets a different code in each area that uses it, but no code twice), and
// every entry pointing at a competency file that exists.
func (c *Catalog) checkAreas(doc Areas) Errors {
	var errs Errors
	seenArea := map[string]string{}
	seenCompCode := map[string]string{}
	for i, a := range doc.Areas {
		path := fmt.Sprintf("%s.areas[%d]", areasPath, i)
		if a.Codigo == "" {
			errs = append(errs, path+".codigo: es obligatorio")
			continue
		}
		if first, dup := seenArea[a.Codigo]; dup {
			errs = append(errs, fmt.Sprintf("%s.codigo: el código de área %q está repetido (ya aparece en %s)", path, a.Codigo, first))
			continue
		}
		seenArea[a.Codigo] = path
		if a.Nombre == "" {
			errs = append(errs, path+".nombre: es obligatorio")
		}
		if len(a.Niveles) == 0 {
			errs = append(errs, path+".niveles: el área debe declarar al menos un nivel")
		}
		for j, n := range a.Niveles {
			if !validNivel(n) {
				errs = append(errs, fmt.Sprintf("%s.niveles[%d]: %q no es un nivel válido; usa inicial, primaria o secundaria", path, j, n))
			}
		}
		if len(a.Competencias) == 0 {
			errs = append(errs, path+".competencias: el área debe tener al menos una competencia")
		}
		codes := map[string]bool{}
		capabilityCodes := map[string]bool{}
		for j, cc := range a.Competencias {
			cpath := fmt.Sprintf("%s.competencias[%d]", path, j)
			if cc.Codigo == "" {
				errs = append(errs, cpath+".codigo: es obligatorio")
				continue
			}
			if codes[cc.Codigo] {
				errs = append(errs, fmt.Sprintf("%s.codigo: el código de competencia %q está repetido en el área %s", cpath, cc.Codigo, a.Codigo))
				continue
			}
			codes[cc.Codigo] = true
			if first, dup := seenCompCode[cc.Codigo]; dup {
				errs = append(errs, fmt.Sprintf("%s.codigo: el código de competencia %q ya está definido en %s; un código no puede aparecer en dos áreas", cpath, cc.Codigo, first))
				continue
			}
			seenCompCode[cc.Codigo] = cpath
			comp, ok := c.Competencias[cc.NumeroCNEB]
			if !ok {
				errs = append(errs, fmt.Sprintf("%s.numero_cneb: la competencia CNEB %d no tiene archivo en %s (se esperaba %s)", cpath, cc.NumeroCNEB, competenciasDir, competenciaFile(cc.NumeroCNEB)))
				continue
			}
			c.NumeroByCode[cc.Codigo] = cc.NumeroCNEB
			for _, cap := range comp.Capacidades {
				capabilityCodes[CapabilityCode(cc.Codigo, cap.Numero)] = true
			}
		}
		c.CapabilityCodesByArea[a.Codigo] = capabilityCodes
		c.Area[a.Codigo] = a
	}
	for i, t := range doc.Transversales {
		path := fmt.Sprintf("%s.transversales[%d]", areasPath, i)
		if t.Codigo == "" {
			errs = append(errs, path+".codigo: es obligatorio")
			continue
		}
		if first, dup := seenCompCode[t.Codigo]; dup {
			errs = append(errs, fmt.Sprintf("%s.codigo: el código de competencia %q ya está definido en %s; un código no puede aparecer en dos áreas", path, t.Codigo, first))
			continue
		}
		seenCompCode[t.Codigo] = path
		if _, ok := c.Competencias[t.NumeroCNEB]; !ok {
			errs = append(errs, fmt.Sprintf("%s.numero_cneb: la competencia CNEB %d no tiene archivo en %s (se esperaba %s)", path, t.NumeroCNEB, competenciasDir, competenciaFile(t.NumeroCNEB)))
			continue
		}
		c.NumeroByCode[t.Codigo] = t.NumeroCNEB
		c.Transversal[t.Codigo] = t
	}
	return errs
}

// competenciaFile is the file a CNEB number is expected to live in.
func competenciaFile(numero int) string {
	return fmt.Sprintf("c%02d.json", numero)
}

func (c *Catalog) gradeList() string {
	codes := make([]string, 0, len(c.Grados))
	for _, g := range c.Grados {
		codes = append(codes, g.Codigo)
	}
	return strings.Join(codes, ", ")
}

func validNivel(n string) bool {
	return n == "inicial" || n == "primaria" || n == "secundaria"
}

func validCiclo(c string) bool {
	switch c {
	case "ciclo_i", "ciclo_ii", "ciclo_iii", "ciclo_iv", "ciclo_v", "ciclo_vi", "ciclo_vii":
		return true
	}
	return false
}

// decodeStrict decodes one catalog file, rejecting unknown keys the way
// onboarding.Decode does: a misspelled "capacidaades" would otherwise drop a
// whole competency's capacities and nobody would notice until a teacher
// cannot pick one.
func decodeStrict[T any](fsys fs.FS, name string, out *T) error {
	raw, err := fs.ReadFile(fsys, name)
	if err != nil {
		return fmt.Errorf("leer %s: %s", name, err)
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(out); err != nil {
		return fmt.Errorf("%s: %s", name, describeDecodeError(raw, err))
	}
	if dec.More() {
		return fmt.Errorf("%s: hay contenido después del objeto JSON principal", name)
	}
	return nil
}

var unknownField = regexp.MustCompile(`unknown field "([^"]+)"`)

func describeDecodeError(raw []byte, err error) string {
	var syntax *json.SyntaxError
	var typ *json.UnmarshalTypeError
	switch {
	case errors.As(err, &syntax):
		return fmt.Sprintf("JSON mal formado en la línea %d: %s", lineOf(raw, syntax.Offset), syntax.Error())
	case errors.As(err, &typ) && typ.Value != "unknown field":
		return fmt.Sprintf("línea %d: el campo %q espera un valor de tipo %s, no %s", lineOf(raw, typ.Offset), typ.Field, typ.Type, typ.Value)
	default:
		if m := unknownField.FindStringSubmatch(err.Error()); m != nil {
			return fmt.Sprintf("campo desconocido %q; revisa el nombre de la clave", m[1])
		}
		return "JSON inválido: " + err.Error()
	}
}

func lineOf(raw []byte, offset int64) int {
	if offset > int64(len(raw)) {
		offset = int64(len(raw))
	}
	return bytes.Count(raw[:offset], []byte("\n")) + 1
}
