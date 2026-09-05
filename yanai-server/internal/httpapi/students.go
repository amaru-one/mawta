package httpapi

import (
	"net/http"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/repo"
)

// competencyIDParam reads the optional ?competency_id=. Absent is legitimate:
// a class whose área has no competencias configured still has a roster, and
// answering with the students and no levels is more useful than an error.
func competencyIDParam(r *http.Request) (*uuid.UUID, bool) {
	raw := strings.TrimSpace(r.URL.Query().Get("competency_id"))
	if raw == "" {
		return nil, true
	}
	parsed, err := uuid.Parse(raw)
	if err != nil {
		return nil, false
	}
	return &parsed, true
}

// GET /classes/{classID}/students?competency_id=&term_id=
//
// The class roster with each student's nivel de logro in one competencia and
// the number of pieces of evidencia behind it.
//
// This replaces reading a roster out of a session, which is what the class list
// had to do before this route existed. Both resolve the same
// section_memberships join; only this one can also answer "and where does each
// of them stand", which took one request per student.
//
// A null level means the teacher has not judged this competencia for this
// student yet — a real state (RVM 048-2024, 5.1.2.2), never a C.
func (a *API) handleClassStudents(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	competencyID, ok := competencyIDParam(r)
	if !ok {
		badRequest(w, "invalid competency_id")
		return
	}
	termIDParam := queryUUID(r, "term_id")

	var students []repo.ClassStudent
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		term, err := repo.ResolveTerm(r.Context(), tx, termIDParam)
		if err != nil {
			return err
		}
		today, err := repo.TenantToday(r.Context(), tx, tc.TenantID)
		if err != nil {
			return err
		}
		students, err = repo.ListClassStudents(r.Context(), tx, classID, competencyID, term.ID, today)
		if err != nil {
			return err
		}
		ids := make([]uuid.UUID, 0, len(students))
		for _, s := range students {
			ids = append(ids, s.StudentID)
		}
		return repo.LogStudentReads(r.Context(), tx, ids, tc.TeacherID, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"students": students})
}

// GET /classes/{classID}/students/{studentID}/evidence?competency_id=&term_id=
//
// The period's evidencia for one student, narrowed to one competencia through
// the criterio tags, each piece carrying its own value on its own scale.
//
// This is the material the teacher reads before asserting the nivel de logro.
// Nothing in the response is aggregated and nothing suggests a level: the norm
// makes that a judgement, not an average (RVM 094-2020, 5.1.1.3 p.2-3).
func (a *API) handleStudentEvidence(w http.ResponseWriter, r *http.Request) {
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
	competencyID, ok := competencyIDParam(r)
	if !ok {
		badRequest(w, "invalid competency_id")
		return
	}
	termIDParam := queryUUID(r, "term_id")

	var evidence []repo.EvaluationEntry
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		term, err := repo.ResolveTerm(r.Context(), tx, termIDParam)
		if err != nil {
			return err
		}
		evidence, err = repo.ListStudentEvidence(r.Context(), tx, classID, studentID, competencyID, term.ID)
		if err != nil {
			return err
		}
		return repo.LogStudentReads(r.Context(), tx, []uuid.UUID{studentID}, tc.TeacherID, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"evidence": evidence})
}
