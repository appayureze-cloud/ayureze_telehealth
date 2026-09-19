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
// envelope-encrypted before being persisted — Postgres never holds
// plaintext key material. The envelope encrypt/decrypt operation itself is
// behind the MasterKeyProvider interface below precisely so the master key
// never has to live in this process's memory as a raw AES key in
// production: EnvMasterKeyProvider (AES-256-GCM under
// API_E2EE_MASTER_KEY_HEX) is a documented local-dev simplification: a
// real deployment swaps in a provider backed by a real KMS/secrets
// manager (AWS KMS, GCP KMS, HashiCorp Vault transit engine — see
// docs/deployment/secrets-management.md for the design and why only the
// provider changes, never internal/sessionsvc or anything that calls
// KeyManager) whose Encrypt/Decrypt calls never expose the master key
// material to this process at all — only the per-call ciphertext.
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

// MasterKeyProvider performs the envelope encrypt/decrypt operation that
// protects session keys at rest. It is the seam between KeyManager (which
// knows nothing about *how* envelope encryption happens) and wherever the
// master key material actually lives — a local env var (EnvMasterKeyProvider,
// below) in this build, or a real KMS/Vault backend in production. Every
// implementation must satisfy the same guarantee EnvMasterKeyProvider does:
// the plaintext session key returned by Decrypt is never logged, persisted,
// or sent anywhere other than back to the authorized caller in
// internal/sessionsvc.
type MasterKeyProvider interface {
	Encrypt(plaintext []byte) ([]byte, error)
	Decrypt(ciphertext []byte) ([]byte, error)
}

// EnvMasterKeyProvider implements MasterKeyProvider with AES-256-GCM using
// a master key held directly in process memory, sourced from
// API_E2EE_MASTER_KEY_HEX. This is the local-dev/test default — see the
// package doc comment and docs/deployment/secrets-management.md for why
// production should use a KMS/Vault-backed MasterKeyProvider instead.
type EnvMasterKeyProvider struct {
	gcm cipher.AEAD
}

func NewEnvMasterKeyProvider(masterKeyHex string) (*EnvMasterKeyProvider, error) {
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
	return &EnvMasterKeyProvider{gcm: gcm}, nil
}

func (p *EnvMasterKeyProvider) Encrypt(plaintext []byte) ([]byte, error) {
	nonce := make([]byte, p.gcm.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return nil, fmt.Errorf("generate nonce: %w", err)
	}
	return p.gcm.Seal(nonce, nonce, plaintext, nil), nil
}

func (p *EnvMasterKeyProvider) Decrypt(encrypted []byte) ([]byte, error) {
	nonceSize := p.gcm.NonceSize()
	if len(encrypted) < nonceSize {
		return nil, errors.New("ciphertext too short")
	}
	nonce, ciphertext := encrypted[:nonceSize], encrypted[nonceSize:]
	plaintext, err := p.gcm.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return nil, fmt.Errorf("decrypt: %w", err)
	}
	return plaintext, nil
}

// KeyManager is the session-key lifecycle API internal/sessionsvc calls —
// it never changes regardless of which MasterKeyProvider backs it, which
// is the whole point of the abstraction: swapping local-dev's env-var
// provider for a production KMS/Vault provider is a one-line change in
// internal/appwire, not a change to any session/consent/auth logic.
type KeyManager struct {
	provider MasterKeyProvider
}

// NewKeyManagerWithProvider builds a KeyManager from any MasterKeyProvider
// — this is what a production deployment wires up with a KMS/Vault-backed
// provider (see docs/deployment/secrets-management.md).
func NewKeyManagerWithProvider(provider MasterKeyProvider) *KeyManager {
	return &KeyManager{provider: provider}
}

// NewKeyManager is the local-dev/test convenience constructor — equivalent
// to NewKeyManagerWithProvider(NewEnvMasterKeyProvider(masterKeyHex)).
func NewKeyManager(masterKeyHex string) (*KeyManager, error) {
	provider, err := NewEnvMasterKeyProvider(masterKeyHex)
	if err != nil {
		return nil, err
	}
	return NewKeyManagerWithProvider(provider), nil
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
	return m.provider.Encrypt(plaintext)
}

func (m *KeyManager) Decrypt(encrypted []byte) ([]byte, error) {
	return m.provider.Decrypt(encrypted)
}
