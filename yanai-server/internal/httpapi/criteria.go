package httpapi

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/db"
	"yanai-server/internal/domain"
	"yanai-server/internal/repo"
)

// GET /classes/{classID}/criteria?student_id=&term_id=
//
// Every competencia of the class's área with the criterios de evaluación the
// teacher has written for it. With student_id, each criterio also carries
// that student's level for the period.
//
// A competencia with no criterios comes back with an empty list rather than
// being omitted: under RVM 094-2020 the criterios are what evidence is judged
// against, so a competencia without any is the thing the teacher most needs
// to see.
func (a *API) handleClassCriteria(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	termIDParam := queryUUID(r, "term_id")

	var studentID *uuid.UUID
	if raw := strings.TrimSpace(r.URL.Query().Get("student_id")); raw != "" {
		parsed, err := uuid.Parse(raw)
		if err != nil {
			badRequest(w, "invalid student_id")
			return
		}
		studentID = &parsed
	}

	var rows []repo.CompetencyCriteriaRow
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		term, err := repo.ResolveTerm(r.Context(), tx, termIDParam)
		if err != nil {
			return err
		}
		rows, err = repo.ListClassCriteria(r.Context(), tx, classID, studentID, term.ID)
		if err != nil {
			return err
		}
		if studentID != nil {
			return repo.LogStudentReads(r.Context(), tx, []uuid.UUID{*studentID}, tc.TeacherID, &classID, nil)
		}
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"competencies": rows})
}

type createCriterionRequest struct {
	Description           string  `json:"description"`
	Code                  *string `json:"code"`
	PerformanceStandardID *string `json:"performance_standard_id"`
}

// POST /classes/{classID}/competencies/{competencyID}/criteria
//
// The teacher writes a criterio for one competencia. This is the "criterios
// are presented by the teacher" path: the text is theirs, optionally anchored
// to a CNEB desempeño.
func (a *API) handleCreateCriterion(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	competencyID, err := pathUUID(r, "competencyID")
	if err != nil {
		badRequest(w, "invalid competencyID")
		return
	}

	var req createCriterionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid body")
		return
	}

	var standardID *uuid.UUID
	if req.PerformanceStandardID != nil && strings.TrimSpace(*req.PerformanceStandardID) != "" {
		parsed, err := uuid.Parse(*req.PerformanceStandardID)
		if err != nil {
			badRequest(w, "invalid performance_standard_id")
			return
		}
		standardID = &parsed
	}

	var criterionID uuid.UUID
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		criterionID, err = repo.CreateCriterion(r.Context(), tx, classID, competencyID,
			req.Code, req.Description, standardID)
		if err != nil {
			return err
		}
		payload, _ := json.Marshal(map[string]any{"competency_id": competencyID})
		return repo.LogEvent(r.Context(), tx, "criterion.created", "evaluation_criterion",
			&criterionID, payload, nil, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": criterionID})
}

// POST /criteria/{criterionID}/delete
func (a *API) handleDeleteCriterion(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	criterionID, err := pathUUID(r, "criterionID")
	if err != nil {
		badRequest(w, "invalid criterionID")
		return
	}

	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := repo.DeleteCriterion(r.Context(), tx, criterionID); err != nil {
			return err
		}
		return repo.LogEvent(r.Context(), tx, "criterion.deleted", "evaluation_criterion",
			&criterionID, nil, nil, nil, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

type assertCriterionLevelRequest struct {
	CriterionID string `json:"criterion_id"`
	// AssessmentID is required: a criterio level always names the evidencia it
	// was read from. There is no term_id — the assessment carries the periodo,
	// and the trigger copies it onto the row.
	AssessmentID string  `json:"assessment_id"`
	Level        string  `json:"level"`
	Note         *string `json:"note"`
}

// POST /classes/{classID}/students/{studentID}/criterion-levels
//
// One cell of the evidencia × criterio grid: what this student showed against
// one criterio, in one piece of evidence. RVM 094-2020 5.1.1.3 p.3 values
// evidence *through* the criterios, so the evidencia is not optional here —
// the criterio is the ruler, never the thing being marked.
//
// This is evidence the teacher accumulates and then weighs; it is never rolled
// up into the competency level automatically, because the norm makes that a
// judgement rather than an average.
func (a *API) handleAssertCriterionLevel(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	studentID, err := pathUUID(r, "studentID")
	if err != nil {
		badRequest(w, "invalid studentID")
		return
	}

	var req assertCriterionLevelRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid body")
		return
	}
	criterionID, err := uuid.Parse(req.CriterionID)
	if err != nil {
		badRequest(w, "invalid criterion_id")
		return
	}
	assessmentID, err := uuid.Parse(req.AssessmentID)
	if err != nil {
		writeAppError(w, db.NewAppError(http.StatusBadRequest, "criterion_level_needs_evidence",
			"a criterio level must name the evidencia it was read from"))
		return
	}
	level := strings.ToUpper(strings.TrimSpace(req.Level))
	switch level {
	case domain.LevelAD, domain.LevelA, domain.LevelB, domain.LevelC:
	default:
		badRequest(w, "level must be AD, A, B or C")
		return
	}

	var levelID uuid.UUID
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		var err error
		levelID, err = repo.AssertCriterionLevel(r.Context(), tx,
			assessmentID, studentID, criterionID, tc.TeacherID, level, req.Note)
		if err != nil {
			return err
		}
		payload, _ := json.Marshal(map[string]any{
			"level": level, "criterion_id": criterionID, "assessment_id": assessmentID,
		})
		return repo.LogEvent(r.Context(), tx, "criterion_level.asserted", "evaluation_criterion_score",
			&levelID, payload, &studentID, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": levelID, "level": level})
}

// GET /assessments/{assessmentID}/criteria-grid
//
// The evidencia × criterio grid for one piece of evidence across its roster:
// the criterios it declares as columns, the students as rows, the levels
// already recorded as cells. This is how a teacher actually marks a set of
// work — one criterio at a time down thirty scripts, not thirty screens.
//
// It carries no mark. The school's numeric system is the other reading of the
// same evidence and is captured on the student's own screen; a /20 box beside
// these pickers would put a number in the teacher's eye at the exact moment
// they are meant to be judging against a criterio.
func (a *API) handleAssessmentCriteriaGrid(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	assessmentID, err := pathUUID(r, "assessmentID")
	if err != nil {
		badRequest(w, "invalid assessmentID")
		return
	}

	var grid repo.AssessmentCriterionGrid
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		grid, err = repo.GetAssessmentCriterionGrid(r.Context(), tx, assessmentID)
		if err != nil {
			return err
		}
		ids := make([]uuid.UUID, 0, len(grid.Students))
		for _, s := range grid.Students {
			ids = append(ids, s.StudentID)
		}
		return repo.LogStudentReads(r.Context(), tx, ids, tc.TeacherID, &grid.ClassID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, grid)
}
