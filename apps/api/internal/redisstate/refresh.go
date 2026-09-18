package redisstate

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
)

var ErrRefreshTokenInvalid = errors.New("refresh token invalid or expired")

type RefreshTokenStore struct {
	client *redis.Client
}

func NewRefreshTokenStore(client *redis.Client) *RefreshTokenStore {
	return &RefreshTokenStore{client: client}
}

type RefreshTokenData struct {
	UserID   string
	TenantID string
}

func key(tokenHash string) string { return "refresh:" + tokenHash }

func hash(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

// Issue mints a new opaque refresh token, stores only its hash in Redis
// (so a Redis dump never contains a usable token), and returns the
// plaintext token to hand to the client.
func (s *RefreshTokenStore) Issue(ctx context.Context, data RefreshTokenData, ttl time.Duration) (string, error) {
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return "", fmt.Errorf("generate refresh token: %w", err)
	}
	token := hex.EncodeToString(raw)

	err := s.client.HSet(ctx, key(hash(token)), map[string]any{
		"user_id":   data.UserID,
		"tenant_id": data.TenantID,
	}).Err()
	if err != nil {
		return "", fmt.Errorf("store refresh token: %w", err)
	}
	if err := s.client.Expire(ctx, key(hash(token)), ttl).Err(); err != nil {
		return "", fmt.Errorf("set refresh token ttl: %w", err)
	}
	return token, nil
}

// Redeem validates and immediately revokes a refresh token (single use —
// each /v1/auth/refresh call issues a fresh one), returning the identity it
// was issued for.
func (s *RefreshTokenStore) Redeem(ctx context.Context, token string) (*RefreshTokenData, error) {
	k := key(hash(token))
	vals, err := s.client.HGetAll(ctx, k).Result()
	if err != nil {
		return nil, fmt.Errorf("lookup refresh token: %w", err)
	}
	if len(vals) == 0 {
		return nil, ErrRefreshTokenInvalid
	}
	_ = s.client.Del(ctx, k).Err()
	return &RefreshTokenData{UserID: vals["user_id"], TenantID: vals["tenant_id"]}, nil
}

func (s *RefreshTokenStore) Revoke(ctx context.Context, token string) error {
	return s.client.Del(ctx, key(hash(token))).Err()
}
