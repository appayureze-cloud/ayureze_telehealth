package httpapi

import (
	"context"
	"errors"
	"net"
	"net/http"
	"strings"

	"github.com/ayureze/telehealth/api/internal/authn"
)

type ctxAuthKey string

const claimsKey ctxAuthKey = "claims"

// RequireAuth parses and verifies the Authorization: Bearer <token> header
// against the platform's own JWT issuer (internal/authn) — distinct from
// LiveKit room-access tokens. Requests without a valid token never reach a
// handler.
func RequireAuth(issuer *authn.Issuer) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			header := r.Header.Get("Authorization")
			const prefix = "Bearer "
			if !strings.HasPrefix(header, prefix) {
				writeError(w, http.StatusUnauthorized, "missing_token", "Authorization: Bearer <token> header required")
				return
			}
			tokenString := strings.TrimPrefix(header, prefix)
			claims, err := issuer.Parse(tokenString)
			if err != nil {
				status := http.StatusUnauthorized
				code := "invalid_token"
				if errors.Is(err, authn.ErrExpiredToken) {
					code = "expired_token"
				}
				writeError(w, status, code, "invalid or expired access token")
				return
			}
			ctx := context.WithValue(r.Context(), claimsKey, claims)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

func ClaimsFromContext(ctx context.Context) (*authn.Claims, bool) {
	c, ok := ctx.Value(claimsKey).(*authn.Claims)
	return c, ok
}

func ClientIP(r *http.Request) string {
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		return strings.TrimSpace(strings.Split(xff, ",")[0])
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}
