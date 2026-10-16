// Package authn issues and verifies the platform's own application-level
// JWTs (distinct from LiveKit's room-access tokens minted in
// internal/token). These carry the user's identity/tenant/role and are
// what every authenticated API request presents.
package authn

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/ayureze/telehealth/api/internal/domain"
)

var (
	ErrInvalidToken = errors.New("invalid token")
	ErrExpiredToken = errors.New("token expired")
)

type Claims struct {
	UserID   string      `json:"uid"`
	TenantID string      `json:"tid"`
	Role     domain.Role `json:"role"`
	jwt.RegisteredClaims
}

type Issuer struct {
	secret []byte
}

func NewIssuer(secret string) *Issuer { return &Issuer{secret: []byte(secret)} }

func (i *Issuer) IssueAccessToken(u domain.User, ttl time.Duration) (string, time.Time, error) {
	now := time.Now()
	exp := now.Add(ttl)
	jti, err := randomID()
	if err != nil {
		return "", time.Time{}, fmt.Errorf("generate token id: %w", err)
	}
	claims := Claims{
		UserID:   u.ID,
		TenantID: u.TenantID,
		Role:     u.Role,
		RegisteredClaims: jwt.RegisteredClaims{
			ID:        jti,
			Subject:   u.ID,
			IssuedAt:  jwt.NewNumericDate(now),
			NotBefore: jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(exp),
		},
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	signed, err := tok.SignedString(i.secret)
	if err != nil {
		return "", time.Time{}, fmt.Errorf("sign access token: %w", err)
	}
	return signed, exp, nil
}

func randomID() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

func (i *Issuer) Parse(tokenString string) (*Claims, error) {
	var claims Claims
	tok, err := jwt.ParseWithClaims(tokenString, &claims, func(t *jwt.Token) (interface{}, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
		}
		return i.secret, nil
	})
	if err != nil {
		if errors.Is(err, jwt.ErrTokenExpired) {
			return nil, ErrExpiredToken
		}
		return nil, fmt.Errorf("%w: %v", ErrInvalidToken, err)
	}
	if !tok.Valid {
		return nil, ErrInvalidToken
	}
	return &claims, nil
}
