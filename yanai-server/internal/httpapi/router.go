// Package httpapi wires the chi router, middleware, and one handler file
// per screen of the app.
package httpapi

import (
	"log/slog"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/go-chi/cors"

	"yanai-server/internal/config"
	"yanai-server/internal/db"
)

type API struct {
	db     *db.DB
	cfg    config.Config
	logger *slog.Logger
}

func New(database *db.DB, cfg config.Config, logger *slog.Logger) *API {
	return &API{db: database, cfg: cfg, logger: logger}
}

func (a *API) Router() http.Handler {
	r := chi.NewRouter()

	r.Use(requestID)
	r.Use(requestLogger(a.logger))
	r.Use(middleware.Recoverer)
	r.Use(cors.Handler(cors.Options{
		AllowedOrigins:   a.cfg.CORSOrigins,
		AllowedMethods:   []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"X-Request-ID", "Content-Type"},
		ExposedHeaders:   []string{"X-Request-ID"},
		AllowCredentials: true,
		MaxAge:           300,
	}))

	r.Get("/healthz", a.handleHealthz)

	r.Route("/api/v1", func(r chi.Router) {
		// Outside sessionAuth by necessity: there is no session yet.
		r.Post("/auth/login", a.handleLogin)
		r.Post("/auth/logout", a.handleLogout)

		// chi panics on Use() after routes are registered on the same
		// router, so the protected surface needs its own Group.
		r.Group(func(r chi.Router) {
			r.Use(a.sessionAuth)

			r.Get("/me", a.handleMe)

			r.Get("/home", a.handleHome)

			r.Get("/classes/{classID}/dashboard", a.handleClassDashboard)
			// The class list, and the evidence one student has in one competencia —
			// the two reads the evaluating screens are built on.
			r.Get("/classes/{classID}/students", a.handleClassStudents)
			r.Get("/classes/{classID}/students/{studentID}/evidence", a.handleStudentEvidence)
			r.Get("/classes/{classID}/students/{studentID}/grades", a.handleStudentGrades)
			r.Get("/classes/{classID}/grading-components", a.handleGradingComponents)
			r.Post("/classes/{classID}/assessments", a.handleCreateAssessment)
			r.Post("/assessments/{assessmentID}/delete", a.handleDeleteAssessment)

			// Niveles de logro: the official MINEDU record (RVM 094-2020 / 048-2024).
			r.Get("/classes/{classID}/students/{studentID}/competencies", a.handleStudentCompetencies)
			r.Post("/classes/{classID}/students/{studentID}/competency-levels", a.handleAssertCompetencyLevel)
			r.Post("/classes/{classID}/students/{studentID}/conclusions", a.handleUpsertConclusion)

			// Criterios de evaluación: what the teacher says to look at in a piece of
			// work. Authoring only — a criterio is a tag on evidencia and is never
			// itself graded, so there is deliberately no level route here.
			r.Get("/classes/{classID}/criteria", a.handleClassCriteria)
			r.Post("/classes/{classID}/competencies/{competencyID}/criteria", a.handleCreateCriterion)
			r.Post("/criteria/{criterionID}/delete", a.handleDeleteCriterion)

			r.Post("/sessions/{sessionID}/start", a.handleSessionStart)
			r.Get("/sessions/{sessionID}", a.handleSessionRoster)
			r.Put("/sessions/{sessionID}/attendance/{studentID}", a.handleAttendanceUpsert)
			r.Post("/sessions/{sessionID}/attendance/mark-all-present", a.handleMarkAllPresent)
			r.Post("/sessions/{sessionID}/students/{studentID}/voice-notes", a.handleCreateVoiceNote)

			r.Get("/voice-notes/{voiceNoteID}/audio", a.handleVoiceNoteAudio)
			r.Post("/voice-notes/{voiceNoteID}/save", a.handleVoiceNoteSave)
			r.Post("/voice-notes/{voiceNoteID}/discard", a.handleVoiceNoteDiscard)

			r.Post("/assessments/{assessmentID}/scores", a.handleCreateScore)
			r.Post("/scores/{scoreID}/correct", a.handleCorrectScore)

			r.Post("/classes/{classID}/students/{studentID}/practice-scores", a.handleCreatePracticeScore)
			r.Post("/practice-scores/{practiceScoreID}/delete", a.handleDeletePracticeScore)

			r.Get("/notifications", a.handleListNotifications)
			r.Post("/notifications/{notificationID}/read", a.handleMarkNotificationRead)
			r.Post("/notifications/read-all", a.handleMarkAllNotificationsRead)

			r.Get("/profile", a.handleProfile)
		})
	})

	return r
}

func (a *API) handleHealthz(w http.ResponseWriter, r *http.Request) {
	if err := a.db.Pool.Ping(r.Context()); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{"ok": false})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}
