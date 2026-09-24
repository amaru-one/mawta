package onboarding

import "strings"

const (
	scaleMinedu    = "minedu_ad_a_b_c"
	scaleVigesimal = "vigesimal_0_20"
)

type scaleLevel struct {
	code, label      string
	ordinal          int
	minNorm, maxNorm float64
	colorKey         string
}

// mineduLevels are the RVM 094-2020 achievement levels. The normalised bands
// only let internal/grading SUGGEST a level from the internal average; the
// teacher asserts the level and may depart from the suggestion.
var mineduLevels = []scaleLevel{
	{"C", "En inicio", 1, 0.00, 0.55, "rojo"},
	{"B", "En proceso", 2, 0.55, 0.70, "ambar"},
	{"A", "Logro esperado", 3, 0.70, 0.85, "verde"},
	{"AD", "Logro destacado", 4, 0.85, 1.00, "azul"},
}

// defaultScheme is the grading scheme an area gets when the file sets none:
// prácticas 40% (the lowest one dropped), exámenes 40%, proyectos 20%.
func defaultScheme(a Area) Esquema {
	return Esquema{
		Codigo:      strings.ToLower(a.Codigo) + "_estandar",
		Nombre:      a.Nombre + " — estándar",
		Descripcion: "Prácticas 40%, exámenes 40%, proyectos 20%.",
		Componentes: []Componente{
			{Codigo: "practicas", Nombre: "Prácticas calificadas", Peso: 0.40, DescartarMasBajas: 1},
			{Codigo: "examenes", Nombre: "Exámenes", Peso: 0.40},
			{Codigo: "proyectos", Nombre: "Proyectos", Peso: 0.20},
		},
	}
}

// schemeFor returns the area's own scheme when the file sets one.
func schemeFor(a Area) Esquema {
	if a.EsquemaCalificacion != nil {
		return *a.EsquemaCalificacion
	}
	return defaultScheme(a)
}
