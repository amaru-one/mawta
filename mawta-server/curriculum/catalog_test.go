package curriculum

import (
	"strings"
	"testing"
	"testing/fstest"
)

// TestShippedCatalogIsValid runs the full validation over the embedded data:
// the catalog is an input this package never edits, so a broken file must
// stop the build here rather than at a school's installation.
func TestShippedCatalogIsValid(t *testing.T) {
	c, err := Load()
	if err != nil {
		t.Fatalf("the shipped catalog must validate: %v", err)
	}
	if c.Fuente == "" {
		t.Error("cneb.json.fuente is empty")
	}
}

// TestShippedCatalogFacts asserts facts about specific shipped competencies,
// not totals: the catalog grows one area at a time and the code must work
// unchanged as areas are added.
func TestShippedCatalogFacts(t *testing.T) {
	c, err := Load()
	if err != nil {
		t.Fatal(err)
	}

	// Competency 23 (Resuelve problemas de cantidad) has 4 capabilities and
	// standards at levels 1-8.
	c23, ok := c.Competencias[23]
	if !ok {
		t.Fatal("competency 23 is missing from the catalog")
	}
	if len(c23.Capacidades) != 4 {
		t.Errorf("competency 23 has %d capabilities, want 4", len(c23.Capacidades))
	}
	levels := map[int]bool{}
	for _, e := range c23.Estandares {
		levels[e.Nivel] = true
	}
	for lvl := 1; lvl <= 8; lvl++ {
		if !levels[lvl] {
			t.Errorf("competency 23 has no standard at level %d", lvl)
		}
	}

	// The transversals have no performances: their performances are per
	// cycle, not per grade, and are deferred.
	for _, code := range []string{"TR-C1", "TR-C2"} {
		comp, ok := c.CompetenciaByCode(code)
		if !ok {
			t.Fatalf("%s is missing from the catalog", code)
		}
		if len(comp.Desempenos) != 0 {
			t.Errorf("%s has %d performances, want 0 (transversal performances are deferred)", code, len(comp.Desempenos))
		}
	}

	// The same CNEB competency appears under a different code in each area
	// that uses it: 17 is PS-C3 in primaria and CCSS-C1 in secundaria.
	if got := c.NumeroByCode["PS-C3"]; got != 17 {
		t.Errorf("PS-C3 maps to CNEB %d, want 17", got)
	}
	if got := c.NumeroByCode["CCSS-C1"]; got != 17 {
		t.Errorf("CCSS-C1 maps to CNEB %d, want 17", got)
	}

	// Capability codes follow the school convention.
	if want := "MAT-C1-CAP1"; !c.CapabilityCodesByArea["MAT"][want] {
		t.Errorf("MAT does not declare capability %s", want)
	}

	// The EBR cycle → level mapping is present for every cycle a grade uses.
	for _, ciclo := range []string{"ciclo_iii", "ciclo_iv", "ciclo_v", "ciclo_vi", "ciclo_vii"} {
		if _, ok := c.ExpectedLevel(DefaultModality, ciclo); !ok {
			t.Errorf("no expected level for (%s, %s)", DefaultModality, ciclo)
		}
	}
	if lvl, _ := c.ExpectedLevel(DefaultModality, "ciclo_vi"); lvl != 6 {
		t.Errorf("(ebr, ciclo_vi) → %d, want 6", lvl)
	}
}

// TestDerivedStance checks the derived en_proceso rule: only the last grade
// of a cycle reaches the cycle standard; earlier grades are in progress
// towards it.
func TestDerivedStance(t *testing.T) {
	c, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	cases := map[string]bool{
		// Cycle III: 1P is in progress, 2P reaches.
		"1P": true, "2P": false,
		// Cycle IV: 3P in progress, 4P reaches.
		"3P": true, "4P": false,
		// Cycle V: 5P in progress, 6P reaches.
		"5P": true, "6P": false,
		// Cycle VI: 1S in progress, 2S reaches.
		"1S": true, "2S": false,
		// Cycle VII: 3S and 4S in progress, 5S reaches.
		"3S": true, "4S": true, "5S": false,
	}
	for grado, want := range cases {
		if got := c.EnProceso(grado); got != want {
			t.Errorf("EnProceso(%s) = %v, want %v", grado, got, want)
		}
	}
	if last, ok := c.LastGradeOfCycle("ciclo_vii"); !ok || last != "5S" {
		t.Errorf("last grade of ciclo_vii = %q, %v; want 5S", last, ok)
	}
}

// catalogFS builds a synthetic filesystem with the given cneb.json and
// areas.json plus one competency file, so each validation error can be
// exercised in isolation.
func catalogFS(t *testing.T, cneb, areas string, competencias map[string]string) fstest.MapFS {
	t.Helper()
	m := fstest.MapFS{
		"cneb/cneb.json":  {Data: []byte(cneb)},
		"cneb/areas.json": {Data: []byte(areas)},
	}
	for name, body := range competencias {
		m["cneb/competencias/"+name] = &fstest.MapFile{Data: []byte(body)}
	}
	return m
}

const (
	minCNEB = `{
  "fuente": "CNEB (RM 281-2016)",
  "grados": [
    {"codigo": "1S", "nivel": "secundaria", "ciclo": "ciclo_vi"},
    {"codigo": "2S", "nivel": "secundaria", "ciclo": "ciclo_vi"}
  ],
  "niveles_esperados": [
    {"modalidad": "ebr", "ciclo": "ciclo_vi", "nivel": 6}
  ]
}`
	minAreas = `{
  "areas": [
    {"codigo": "MAT", "nombre": "Matemática", "niveles": ["secundaria"],
     "competencias": [{"codigo": "MAT-C1", "numero_cneb": 23}]}
  ],
  "transversales": [{"codigo": "TR-C1", "numero_cneb": 28}]
}`
	minComp23 = `{
  "numero_cneb": 23,
  "nombre": "Resuelve problemas de cantidad",
  "capacidades": [{"numero": 1, "nombre": "Traduce cantidades"}],
  "estandares": [{"nivel": 6, "texto": "Estándar de nivel 6."}],
  "desempenos": [{"grado": "1S", "orden": 1, "texto": "Primer desempeño."}]
}`
	minComp28 = `{
  "numero_cneb": 28,
  "nombre": "Se desenvuelve en los entornos virtuales generados por las TIC",
  "capacidades": [{"numero": 1, "nombre": "Personaliza entornos virtuales"}],
  "estandares": [{"nivel": 6, "texto": "Estándar de nivel 6."}]
}`
)

func validCatalogFS(t *testing.T) fstest.MapFS {
	return catalogFS(t, minCNEB, minAreas, map[string]string{
		"c23.json": minComp23,
		"c28.json": minComp28,
	})
}

func TestMinimalCatalogLoads(t *testing.T) {
	if _, err := loadFS(validCatalogFS(t)); err != nil {
		t.Fatalf("a consistent minimal catalog must load: %v", err)
	}
}

func TestCatalogValidationErrors(t *testing.T) {
	cases := []struct {
		name string
		fsys func(t *testing.T) fstest.MapFS
		want string
	}{
		{
			name: "missing cneb.json",
			fsys: func(t *testing.T) fstest.MapFS {
				f := validCatalogFS(t)
				delete(f, "cneb/cneb.json")
				return f
			},
			want: "leer cneb/cneb.json",
		},
		{
			name: "missing areas.json",
			fsys: func(t *testing.T) fstest.MapFS {
				f := validCatalogFS(t)
				delete(f, "cneb/areas.json")
				return f
			},
			want: "leer cneb/areas.json",
		},
		{
			name: "missing competency file",
			fsys: func(t *testing.T) fstest.MapFS {
				f := validCatalogFS(t)
				delete(f, "cneb/competencias/c28.json")
				return f
			},
			want: `la competencia CNEB 28 no tiene archivo en cneb/competencias (se esperaba c28.json)`,
		},
		{
			name: "duplicate grade code",
			fsys: func(t *testing.T) fstest.MapFS {
				return catalogFS(t, strings.Replace(minCNEB,
					`{"codigo": "2S", "nivel": "secundaria", "ciclo": "ciclo_vi"}`,
					`{"codigo": "1S", "nivel": "secundaria", "ciclo": "ciclo_vi"}`, 1),
					minAreas, map[string]string{"c23.json": minComp23, "c28.json": minComp28})
			},
			want: `el grado "1S" está repetido`,
		},
		{
			name: "cycle missing from niveles_esperados",
			fsys: func(t *testing.T) fstest.MapFS {
				return catalogFS(t, strings.Replace(minCNEB,
					`{"modalidad": "ebr", "ciclo": "ciclo_vi", "nivel": 6}`, "", 1),
					minAreas, map[string]string{"c23.json": minComp23, "c28.json": minComp28})
			},
			want: `falta el ciclo "ciclo_vi"`,
		},
		{
			name: "duplicate area code",
			fsys: func(t *testing.T) fstest.MapFS {
				return catalogFS(t, minCNEB, strings.Replace(minAreas,
					`"competencias": [{"codigo": "MAT-C1", "numero_cneb": 23}]}
  ]`,
					`"competencias": [{"codigo": "MAT-C1", "numero_cneb": 23}]},
    {"codigo": "MAT", "nombre": "Matemática 2", "niveles": ["secundaria"],
     "competencias": [{"codigo": "MAT-C9", "numero_cneb": 23}]}
  ]`, 1),
					map[string]string{"c23.json": minComp23, "c28.json": minComp28})
			},
			want: `el código de área "MAT" está repetido`,
		},
		{
			name: "duplicate competency code across areas",
			fsys: func(t *testing.T) fstest.MapFS {
				return catalogFS(t, minCNEB, strings.Replace(minAreas,
					`"competencias": [{"codigo": "MAT-C1", "numero_cneb": 23}]}
  ]`,
					`"competencias": [{"codigo": "MAT-C1", "numero_cneb": 23}]},
    {"codigo": "EF", "nombre": "Educación Física", "niveles": ["secundaria"],
     "competencias": [{"codigo": "MAT-C1", "numero_cneb": 23}]}
  ]`, 1),
					map[string]string{"c23.json": minComp23, "c28.json": minComp28})
			},
			want: `el código de competencia "MAT-C1" ya está definido`,
		},
		{
			name: "duplicate transversal code",
			fsys: func(t *testing.T) fstest.MapFS {
				return catalogFS(t, minCNEB, strings.Replace(minAreas,
					`"transversales": [{"codigo": "TR-C1", "numero_cneb": 28}]`,
					`"transversales": [{"codigo": "TR-C1", "numero_cneb": 28},
                       {"codigo": "TR-C1", "numero_cneb": 29}]`, 1),
					map[string]string{"c23.json": minComp23, "c28.json": minComp28, "c29.json": minComp28})
			},
			want: `el código de competencia "TR-C1" ya está definido`,
		},
		{
			name: "duplicate CNEB number in two files",
			fsys: func(t *testing.T) fstest.MapFS {
				f := validCatalogFS(t)
				f["cneb/competencias/c29.json"] = f["cneb/competencias/c28.json"]
				return f
			},
			want: "la competencia 28 está repetida",
		},
		{
			name: "competency without capabilities",
			fsys: func(t *testing.T) fstest.MapFS {
				return catalogFS(t, minCNEB, minAreas, map[string]string{
					"c23.json": strings.Replace(minComp23, `"capacidades": [{"numero": 1, "nombre": "Traduce cantidades"}],`, "", 1),
					"c28.json": minComp28,
				})
			},
			want: "la competencia debe tener al menos una capacidad",
		},
		{
			name: "standard level outside 1-8",
			fsys: func(t *testing.T) fstest.MapFS {
				return catalogFS(t, minCNEB, minAreas, map[string]string{
					"c23.json": strings.Replace(minComp23, `"nivel": 6`, `"nivel": 9`, 1),
					"c28.json": minComp28,
				})
			},
			want: "9 no está entre 1 y 8",
		},
		{
			name: "repeated standard level",
			fsys: func(t *testing.T) fstest.MapFS {
				return catalogFS(t, minCNEB, minAreas, map[string]string{
					"c23.json": strings.Replace(minComp23,
						`"estandares": [{"nivel": 6, "texto": "Estándar de nivel 6."}]`,
						`"estandares": [{"nivel": 6, "texto": "uno"}, {"nivel": 6, "texto": "dos"}]`, 1),
					"c28.json": minComp28,
				})
			},
			want: "el nivel 6 está repetido",
		},
		{
			name: "performance with an unknown grade",
			fsys: func(t *testing.T) fstest.MapFS {
				return catalogFS(t, minCNEB, minAreas, map[string]string{
					"c23.json": strings.Replace(minComp23, `"grado": "1S"`, `"grado": "9S"`, 1),
					"c28.json": minComp28,
				})
			},
			want: `"9S" no es un grado del catálogo`,
		},
		{
			name: "repeated orden within one competency and grade",
			fsys: func(t *testing.T) fstest.MapFS {
				return catalogFS(t, minCNEB, minAreas, map[string]string{
					"c23.json": strings.Replace(minComp23,
						`"desempenos": [{"grado": "1S", "orden": 1, "texto": "Primer desempeño."}]`,
						`"desempenos": [{"grado": "1S", "orden": 1, "texto": "uno"},
                        {"grado": "1S", "orden": 1, "texto": "dos"}]`, 1),
					"c28.json": minComp28,
				})
			},
			want: `el orden 1 del grado "1S" está repetido`,
		},
		{
			name: "capacidad_sugerida from another competency",
			fsys: func(t *testing.T) fstest.MapFS {
				return catalogFS(t, minCNEB, minAreas, map[string]string{
					"c23.json": strings.Replace(minComp23,
						`"texto": "Primer desempeño."}`,
						`"texto": "Primer desempeño.", "capacidad_sugerida": 7}`, 1),
					"c28.json": minComp28,
				})
			},
			want: "7 no es una capacidad de la competencia 23",
		},
		{
			name: "unknown JSON key",
			fsys: func(t *testing.T) fstest.MapFS {
				return catalogFS(t, minCNEB, minAreas, map[string]string{
					"c23.json": strings.Replace(minComp23, `"numero_cneb": 23`, `"numero_cnneb": 23`, 1),
					"c28.json": minComp28,
				})
			},
			want: `campo desconocido "numero_cnneb"`,
		},
		{
			name: "file name does not match the CNEB number",
			fsys: func(t *testing.T) fstest.MapFS {
				f := validCatalogFS(t)
				f["cneb/competencias/c24.json"] = f["cneb/competencias/c23.json"]
				delete(f, "cneb/competencias/c23.json")
				return f
			},
			want: `el archivo se llama "c24.json" pero la competencia dice ser la número 23`,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := loadFS(tc.fsys(t))
			if err == nil {
				t.Fatal("want a validation error, got none")
			}
			if !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("want an error containing %q, got:\n%s", tc.want, err)
			}
		})
	}
}

// TestDecodeRejectsTrailingContent guards against a file that is two objects
// glued together, which a strict decoder would otherwise read as one.
func TestDecodeRejectsTrailingContent(t *testing.T) {
	f := validCatalogFS(t)
	f["cneb/competencias/c23.json"] = &fstest.MapFile{Data: []byte(minComp23 + "\n{}")}
	_, err := loadFS(f)
	if err == nil || !strings.Contains(err.Error(), "después del objeto JSON principal") {
		t.Fatalf("want trailing-content error, got %v", err)
	}
}
