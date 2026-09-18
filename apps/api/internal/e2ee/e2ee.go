// Package e2ee manages the lifecycle of per-session media-encryption key
// material on the application side.
//
// IMPORTANT — what this package does and does not provide:
//
// LiveKit (the SFU) never has access to session media keys in either case
// below. Actual frame encryption/decryption happens in the LiveKit client
// SDKs (SFrame), using a shared session key distributed by this API. This
// package is the *key lifecycle* (generate, envelope-encrypt at rest,
// distribute on authorized join, invalidate) — not the SFrame
// implementation itself, which lives in the client SDKs (sdk/web,
// sdk/flutter, Day 7).
//
// The raw per-session key is generated once at session creation and
// envelope-encrypted (AES-256-GCM) under API_E2EE_MASTER_KEY_HEX before
// being persisted — Postgres never holds plaintext key material. The
// master key itself is expected to come from a real KMS/secrets manager in
// production; a static env var is a documented local-dev simplification
// (see docs/e2ee/README.md).
//
// Keys are never logged — see internal/logging's redaction and
// docs/monitoring/privacy.md.
package e2ee

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
)

const KeySize = 32 // AES-256 / SFrame-compatible key length

var ErrInvalidMasterKey = errors.New("E2EE master key must be 32 bytes (64 hex chars)")

type KeyManager struct {
	gcm cipher.AEAD
}

func NewKeyManager(masterKeyHex string) (*KeyManager, error) {
	raw, err := hex.DecodeString(masterKeyHex)
	if err != nil || len(raw) != KeySize {
		return nil, ErrInvalidMasterKey
	}
	block, err := aes.NewCipher(raw)
	if err != nil {
		return nil, fmt.Errorf("init cipher: %w", err)
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("init gcm: %w", err)
	}
	return &KeyManager{gcm: gcm}, nil
}

// GenerateSessionKey produces a new random session E2EE key, already
// envelope-encrypted for storage. The caller must not log or persist the
// plaintext return value.
func (m *KeyManager) GenerateSessionKey() (plaintext []byte, encrypted []byte, err error) {
	plaintext = make([]byte, KeySize)
	if _, err := rand.Read(plaintext); err != nil {
		return nil, nil, fmt.Errorf("generate key: %w", err)
	}
	encrypted, err = m.Encrypt(plaintext)
	if err != nil {
		return nil, nil, err
	}
	return plaintext, encrypted, nil
}

func (m *KeyManager) Encrypt(plaintext []byte) ([]byte, error) {
	nonce := make([]byte, m.gcm.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return nil, fmt.Errorf("generate nonce: %w", err)
	}
	return m.gcm.Seal(nonce, nonce, plaintext, nil), nil
}

func (m *KeyManager) Decrypt(encrypted []byte) ([]byte, error) {
	nonceSize := m.gcm.NonceSize()
	if len(encrypted) < nonceSize {
		return nil, errors.New("ciphertext too short")
	}
	nonce, ciphertext := encrypted[:nonceSize], encrypted[nonceSize:]
	plaintext, err := m.gcm.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return nil, fmt.Errorf("decrypt: %w", err)
	}
	return plaintext, nil
}
