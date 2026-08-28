// Package httpapi wires the chi router, middleware, and one handler file
// per screen of yanai-views.html.
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
		AllowedHeaders:   []string{"X-Tenant-ID", "X-Actor-ID", "X-Request-ID", "Content-Type"},
		ExposedHeaders:   []string{"X-Request-ID"},
		AllowCredentials: false,
		MaxAge:           300,
	}))

	r.Get("/healthz", a.handleHealthz)

	r.Route("/api/v1", func(r chi.Router) {
		r.Use(a.tenantAuth)

		r.Get("/me", a.handleMe)
		r.Get("/flag-types", a.handleListFlagTypes)

		r.Get("/home", a.handleHome)
		r.Get("/classes", a.handleSearchClasses)

		r.Get("/classes/{classID}/dashboard", a.handleClassDashboard)
		r.Get("/classes/{classID}/sessions", a.handleClassSessions)
		r.Get("/classes/{classID}/students/{studentID}/grades", a.handleStudentGrades)
		r.Post("/classes/{classID}/assessments", a.handleCreateAssessment)
		r.Post("/classes/{classID}/students/{studentID}/summary", a.handleRequestSummary)

		// Niveles de logro: the official MINEDU record (RVM 094-2020 / 048-2024).
		r.Get("/classes/{classID}/students/{studentID}/competencies", a.handleStudentCompetencies)
		r.Post("/classes/{classID}/students/{studentID}/competency-levels", a.handleAssertCompetencyLevel)
		r.Post("/classes/{classID}/students/{studentID}/conclusions", a.handleUpsertConclusion)
		r.Get("/classes/{classID}/siagie-report", a.handleSiagieReport)

		// Criterios de evaluación: what the teacher judges each competencia
		// against, and the per-criterio levels that evidence the judgement.
		r.Get("/classes/{classID}/criteria", a.handleClassCriteria)
		r.Post("/classes/{classID}/competencies/{competencyID}/criteria", a.handleCreateCriterion)
		r.Post("/criteria/{criterionID}/delete", a.handleDeleteCriterion)
		r.Post("/classes/{classID}/students/{studentID}/criterion-levels", a.handleAssertCriterionLevel)

		r.Post("/sessions/{sessionID}/start", a.handleSessionStart)
		r.Post("/sessions/{sessionID}/complete", a.handleSessionComplete)
		r.Get("/sessions/{sessionID}", a.handleSessionRoster)
		r.Put("/sessions/{sessionID}/attendance/{studentID}", a.handleAttendanceUpsert)
		r.Post("/sessions/{sessionID}/attendance/mark-all-present", a.handleMarkAllPresent)
		r.Put("/sessions/{sessionID}/observations/{studentID}", a.handleObservationUpsert)
		r.Post("/sessions/{sessionID}/students/{studentID}/voice-notes", a.handleCreateVoiceNote)

		r.Get("/voice-notes/{voiceNoteID}/audio", a.handleVoiceNoteAudio)
		r.Post("/voice-notes/{voiceNoteID}/transcript", a.handleVoiceNoteTranscript)
		r.Post("/voice-notes/{voiceNoteID}/save", a.handleVoiceNoteSave)
		r.Post("/voice-notes/{voiceNoteID}/discard", a.handleVoiceNoteDiscard)

		r.Post("/assessments/{assessmentID}/scores", a.handleCreateScore)
		r.Post("/scores/{scoreID}/correct", a.handleCorrectScore)

		r.Post("/classes/{classID}/students/{studentID}/practice-scores", a.handleCreatePracticeScore)
		r.Post("/practice-scores/{practiceScoreID}/delete", a.handleDeletePracticeScore)

		r.Get("/notifications", a.handleListNotifications)
		r.Get("/notifications/unread-count", a.handleUnreadCount)
		r.Post("/notifications/{notificationID}/read", a.handleMarkNotificationRead)
		r.Post("/notifications/read-all", a.handleMarkAllNotificationsRead)
		r.Post("/notifications/{notificationID}/dismiss", a.handleDismissNotification)

		r.Get("/profile", a.handleProfile)
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
