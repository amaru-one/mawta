package planning

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/agent"
	"mawta-server/internal/agent/llm"
	"mawta-server/internal/repo"
)

const dateLayout = "2006-01-02"

type experienceState struct {
	Offered map[uuid.UUID]bool
	Chosen  []uuid.UUID
	Term    repo.PlanTerm
}

// Proposal is an experience proposal: shown for review, never saved by the
// agent (the teacher saves it with POST /classes/{id}/experiences).
type Proposal struct {
	Title         string      `json:"title"`
	SituationText string      `json:"situation_text"`
	CompetencyIDs []uuid.UUID `json:"competency_ids"`
	StartsOn      string      `json:"starts_on"`
	EndsOn        string      `json:"ends_on"`
}

var experienceTool = llm.Tool{
	Name:        "proponer_experiencia",
	Description: "Registra la propuesta de experiencia de aprendizaje para la revisión del docente.",
	Properties: map[string]any{
		"title":          map[string]any{"type": "string", "description": "Título corto de la experiencia (máximo 8 palabras)."},
		"situation_text": map[string]any{"type": "string", "description": "Situación significativa de 3 a 6 oraciones, con una o dos preguntas retadoras al final."},
		"competency_ids": map[string]any{"type": "array", "items": map[string]any{"type": "string"}, "description": "Ids de las competencias del área que trabaja la experiencia."},
		"starts_on":      map[string]any{"type": "string", "description": "Primer día, YYYY-MM-DD, dentro de una ventana libre."},
		"ends_on":        map[string]any{"type": "string", "description": "Último día, YYYY-MM-DD, dentro de la misma ventana libre."},
	},
	Required: []string{"title", "situation_text", "competency_ids", "starts_on", "ends_on"},
}

func prepareExperience(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration) (agent.Prepared, error) {
	var in ExperienceInput
	if err := json.Unmarshal(gen.Input, &in); err != nil {
		return agent.Prepared{}, unprocessable("bad_request", "el pedido de propuesta no es válido")
	}
	cur, err := repo.GetCurriculum(ctx, tx, gen.ClassID)
	if err != nil {
		return agent.Prepared{}, err
	}
	term, err := repo.ResolvePlanTerm(ctx, tx, gen.ClassID, in.TermID, time.Now())
	if err != nil {
		return agent.Prepared{}, err
	}
	plan, err := repo.GetPlan(ctx, tx, gen.ClassID, term)
	if err != nil {
		return agent.Prepared{}, err
	}
	windows, err := usableWindows(ctx, tx, gen.ClassID, term)
	if err != nil {
		return agent.Prepared{}, err
	}
	if len(windows) == 0 {
		return agent.Prepared{}, unprocessable("no_free_weeks",
			"No quedan semanas libres en este periodo para una experiencia nueva.")
	}

	offered := map[uuid.UUID]bool{}
	for _, c := range cur.Competencies {
		offered[c.ID] = true
	}
	for _, id := range in.CompetencyIDs {
		if !offered[id] {
			return agent.Prepared{}, unprocessable("competency_not_in_subject", "esa competencia no es del área de esta clase")
		}
	}
	status := map[uuid.UUID]string{}
	for _, c := range plan.Competencies {
		status[c.ID] = c.Status
	}

	var ctxText strings.Builder
	fmt.Fprintf(&ctxText, "<curriculo grado=%q>\n", cur.Grade.Code)
	for _, c := range cur.Competencies {
		fmt.Fprintf(&ctxText, "Competencia id=%s: %s\n", c.ID, c.Name)
		for _, cap := range c.Capabilities {
			fmt.Fprintf(&ctxText, "  - Capacidad: %s\n", cap.Name)
		}
		for _, p := range c.Performances {
			fmt.Fprintf(&ctxText, "  - Desempeño del grado: %s\n", p.Text)
		}
	}
	ctxText.WriteString("</curriculo>")

	var pr strings.Builder
	fmt.Fprintf(&pr, "Periodo: %s, del %s al %s.\n\n", term.Name, term.StartsOn, term.EndsOn)
	pr.WriteString("Ventanas libres (sin otra experiencia), con sus días de clase:\n")
	for _, w := range windows {
		fmt.Fprintf(&pr, "- del %s al %s: %d días de clase\n", w.StartsOn, w.EndsOn, w.ClassDates)
	}
	pr.WriteString("\nSeguimiento de competencias en el año:\n")
	for _, c := range cur.Competencies {
		fmt.Fprintf(&pr, "- id=%s %s: %s\n", c.ID, c.Name, statusText(status[c.ID]))
	}
	if len(in.CompetencyIDs) > 0 {
		pr.WriteString("\nEl docente eligió estas competencias (usa exactamente estas): ")
		for i, id := range in.CompetencyIDs {
			if i > 0 {
				pr.WriteString(", ")
			}
			pr.WriteString(id.String())
		}
		pr.WriteString("\n")
	} else {
		pr.WriteString("\nEl docente no eligió competencias: elige tú entre 1 y 3 del área.\n")
	}
	fmt.Fprintf(&pr, "\n<idea_del_docente>\n%s\n</idea_del_docente>\n", strings.TrimSpace(in.IdeaText))

	return agent.Prepared{
		Spec: &agent.Spec{
			System:    system("experience", ctxText.String()),
			Prompt:    pr.String(),
			Tool:      experienceTool,
			MaxTokens: 1500,
		},
		State: experienceState{Offered: offered, Chosen: in.CompetencyIDs, Term: term},
	}, nil
}

func statusText(s string) string {
	switch s {
	case "toca":
		return "toca este trimestre"
	case "planificada":
		return "ya planificada en este trimestre"
	default:
		return "puede esperar"
	}
}

func applyExperience(ctx context.Context, tx pgx.Tx, gen repo.AgentGeneration, p agent.Prepared, answer json.RawMessage) (json.RawMessage, error) {
	st := p.State.(experienceState)
	var a struct {
		Title         string   `json:"title"`
		SituationText string   `json:"situation_text"`
		CompetencyIDs []string `json:"competency_ids"`
		StartsOn      string   `json:"starts_on"`
		EndsOn        string   `json:"ends_on"`
	}
	if err := decode(answer, &a); err != nil {
		return nil, err
	}
	title, situation := clean(a.Title), strings.TrimSpace(a.SituationText)
	if title == "" || situation == "" {
		return nil, agent.Invalid("title y situation_text son obligatorios y no pueden ir vacíos")
	}

	competencies := st.Chosen
	if len(competencies) == 0 {
		seen := map[uuid.UUID]bool{}
		for _, s := range a.CompetencyIDs {
			id, err := uuid.Parse(strings.TrimSpace(s))
			if err != nil || !st.Offered[id] || seen[id] {
				continue
			}
			seen[id] = true
			competencies = append(competencies, id)
		}
		if len(competencies) == 0 {
			return nil, agent.Invalid("competency_ids debe tener al menos un id de competencia de la lista del currículo")
		}
	}

	start, errS := time.Parse(dateLayout, strings.TrimSpace(a.StartsOn))
	end, errE := time.Parse(dateLayout, strings.TrimSpace(a.EndsOn))
	if errS != nil || errE != nil {
		return nil, agent.Invalid("starts_on y ends_on deben ser fechas YYYY-MM-DD")
	}
	windows, err := usableWindows(ctx, tx, gen.ClassID, st.Term)
	if err != nil {
		return nil, err
	}
	start, end, ok := fitDates(windows, start, end)
	if !ok {
		return nil, unprocessable("no_free_weeks", "No quedan semanas libres en este periodo para una experiencia nueva.")
	}

	return result(map[string]any{"proposal": Proposal{
		Title:         title,
		SituationText: situation,
		CompetencyIDs: competencies,
		StartsOn:      start.Format(dateLayout),
		EndsOn:        end.Format(dateLayout),
	}})
}

type window struct {
	repo.FreeWindow
	from, to time.Time
}

// usableWindows are the term's free stretches that hold at least one class
// date: an experience in a stretch without classes could not be taught.
func usableWindows(ctx context.Context, tx pgx.Tx, classID uuid.UUID, term repo.PlanTerm) ([]window, error) {
	free, err := repo.FreeWindows(ctx, tx, classID, term)
	if err != nil {
		return nil, err
	}
	var out []window
	for _, w := range free {
		if w.ClassDates == 0 {
			continue
		}
		from, _ := time.Parse(dateLayout, w.StartsOn)
		to, _ := time.Parse(dateLayout, w.EndsOn)
		out = append(out, window{FreeWindow: w, from: from, to: to})
	}
	return out, nil
}

// fitDates keeps the model's dates when they lie inside one free window, and
// otherwise moves them to the nearest window, keeping the requested length
// as far as the window allows. The model picks; the server guarantees the
// proposal can actually be saved (no overlap, inside the term).
func fitDates(windows []window, start, end time.Time) (time.Time, time.Time, bool) {
	if len(windows) == 0 {
		return start, end, false
	}
	for _, w := range windows {
		if !start.Before(w.from) && !end.After(w.to) && !end.Before(start) {
			return start, end, true
		}
	}
	days := int(end.Sub(start).Hours()/24) + 1
	if days < 1 || days > 60 {
		days = 14
	}
	best := windows[0]
	bestDist := distance(start, best)
	for _, w := range windows[1:] {
		if d := distance(start, w); d < bestDist {
			best, bestDist = w, d
		}
	}
	// Stay as close to the requested dates as the window allows: a window
	// before them is used from its end backwards, one after them from its
	// start, one holding the start from that start.
	var s, e time.Time
	switch {
	case start.After(best.to):
		e = best.to
		s = e.AddDate(0, 0, -(days - 1))
		if s.Before(best.from) {
			s = best.from
		}
	case start.Before(best.from):
		s = best.from
		e = s.AddDate(0, 0, days-1)
	default:
		s = start
		e = s.AddDate(0, 0, days-1)
	}
	if e.After(best.to) {
		e = best.to
	}
	return s, e, true
}

// distance is how far a date is from a window, in days (0 inside it).
func distance(d time.Time, w window) float64 {
	switch {
	case d.Before(w.from):
		return w.from.Sub(d).Hours() / 24
	case d.After(w.to):
		return d.Sub(w.to).Hours() / 24
	}
	return 0
}
