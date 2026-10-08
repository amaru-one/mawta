package onboarding

const scaleMinedu = "minedu_ad_a_b_c"

type scaleLevel struct {
	code, label      string
	ordinal          int
	minNorm, maxNorm float64
	colorKey         string
}

// mineduLevels are the RVM 094-2020 achievement levels. The normalised bands
// are presentation only: the teacher asserts the level, and nothing derives it
// from a mark.
var mineduLevels = []scaleLevel{
	{"C", "En inicio", 1, 0.00, 0.55, "rojo"},
	{"B", "En proceso", 2, 0.55, 0.70, "ambar"},
	{"A", "Logro esperado", 3, 0.70, 0.85, "verde"},
	{"AD", "Logro destacado", 4, 0.85, 1.00, "azul"},
}
