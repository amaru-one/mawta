package httpapi

import (
	"net/http"
	"time"

	"github.com/jackc/pgx/v5"

	"mawta-server/internal/repo"
)

// Term planning: "Tu trimestre", the curriculum and calendar it is planned
// against, and the learning experiences themselves. The contract is
// docs/api-planificacion.md. Every route reaches a class — directly or
// through an experience, criterion or evidence — and is guarded by
// requireClassAccess on that class.

// GET /classes/{classID}/plan?term_id=
//
// "Tu trimestre". Without term_id, the term that contains today, or else the
// next one.
func (a *API) handleClassPlan(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	termIDParam := queryUUID(r, "term_id")

	var plan repo.Plan
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireClassAccess(r.Context(), tx, tc, classID); err != nil {
			return err
		}
		today, err := repo.TenantToday(r.Context(), tx, tc.TenantID)
		if err != nil {
			return err
		}
		term, err := repo.ResolvePlanTerm(r.Context(), tx, classID, termIDParam, today)
		if err != nil {
			return err
		}
		plan, err = repo.GetPlan(r.Context(), tx, classID, term)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, plan)
}

// GET /classes/{classID}/curriculum
//
// The competencies of the class's área, each with its capabilities and the
// performances of the class's grade. No standards: criteria never come from
// them.
func (a *API) handleClassCurriculum(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	var out repo.Curriculum
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireClassAccess(r.Context(), tx, tc, classID); err != nil {
			return err
		}
		var err error
		out, err = repo.GetCurriculum(r.Context(), tx, classID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// GET /classes/{classID}/calendar?from=&to=
//
// Class dates and non-teaching days in a range at most one term long, for
// choosing experience dates and laying out sessions.
func (a *API) handleClassCalendar(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	from, err := time.Parse(dateLayout, r.URL.Query().Get("from"))
	if err != nil {
		badRequest(w, "from must be a YYYY-MM-DD date")
		return
	}
	to, err := time.Parse(dateLayout, r.URL.Query().Get("to"))
	if err != nil {
		badRequest(w, "to must be a YYYY-MM-DD date")
		return
	}

	var out repo.Calendar
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireClassAccess(r.Context(), tx, tc, classID); err != nil {
			return err
		}
		var err error
		out, err = repo.GetCalendar(r.Context(), tx, classID, from, to)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// GET /experiences/{experienceID}
//
// The whole experience, with the warnings the summary screen shows.
func (a *API) handleGetExperience(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	experienceID, err := pathUUID(r, "experienceID")
	if err != nil {
		badRequest(w, "invalid experienceID")
		return
	}
	var out repo.Experience
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if _, err := a.requireExperienceAccess(r.Context(), tx, tc, experienceID); err != nil {
			return err
		}
		var err error
		out, err = repo.GetExperience(r.Context(), tx, experienceID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// dateLayout is how planning dates travel: YYYY-MM-DD.
const dateLayout = "2006-01-02"
