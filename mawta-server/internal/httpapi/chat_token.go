package httpapi

import (
	"net/http"
	"time"

	"mawta-server/internal/db"
)

type chatTokenResponse struct {
	Token     string    `json:"token"`
	ExpiresAt time.Time `json:"expires_at"`
}

// handleChatToken issues the token the director's browser sends to the chat
// service. The browser asks again before it expires, with the same session
// cookie, so a logout or a revoked role stops new tokens at once. Without a
// signing key it answers 503 chat_unavailable, so the director screen can say
// the chat is not available yet.
func (a *API) handleChatToken(w http.ResponseWriter, r *http.Request) {
	if a.chatTokens == nil {
		writeAppError(w, db.NewAppError(http.StatusServiceUnavailable, "chat_unavailable", "el chat de dirección aún no está disponible"))
		return
	}
	tc := tenantCtxFrom(r)
	token, expiresAt, err := a.chatTokens.Issue(tc.ActorID, tc.TenantID, tc.Role, time.Now())
	if err != nil {
		writeError(w, err)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, chatTokenResponse{Token: token, ExpiresAt: expiresAt})
}
