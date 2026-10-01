package e2ee

import (
	"bytes"
	"strings"
	"testing"
)

func validMasterKeyHex() string {
	return strings.Repeat("ab", KeySize) // 32 bytes of 0xab, 64 hex chars
}

func TestNewKeyManager_RejectsWrongLengthKey(t *testing.T) {
	if _, err := NewKeyManager("deadbeef"); err != ErrInvalidMasterKey {
		t.Fatalf("expected ErrInvalidMasterKey for a short key, got %v", err)
	}
	if _, err := NewKeyManager("not-hex-at-all"); err != ErrInvalidMasterKey {
		t.Fatalf("expected ErrInvalidMasterKey for non-hex input, got %v", err)
	}
}

func TestGenerateSessionKey_RoundTripsThroughEncryptDecrypt(t *testing.T) {
	m, err := NewKeyManager(validMasterKeyHex())
	if err != nil {
		t.Fatalf("NewKeyManager: %v", err)
	}

	plaintext, encrypted, err := m.GenerateSessionKey()
	if err != nil {
		t.Fatalf("GenerateSessionKey: %v", err)
	}
	if len(plaintext) != KeySize {
		t.Fatalf("expected a %d-byte key, got %d", KeySize, len(plaintext))
	}
	if bytes.Contains(encrypted, plaintext) {
		t.Fatal("encrypted key material must not contain the plaintext key as a substring")
	}

	decrypted, err := m.Decrypt(encrypted)
	if err != nil {
		t.Fatalf("Decrypt: %v", err)
	}
	if !bytes.Equal(plaintext, decrypted) {
		t.Fatal("decrypted key does not match the originally generated key")
	}
}

func TestEncrypt_ProducesDistinctCiphertextsForSamePlaintext(t *testing.T) {
	m, err := NewKeyManager(validMasterKeyHex())
	if err != nil {
		t.Fatalf("NewKeyManager: %v", err)
	}
	plaintext := []byte("01234567890123456789012345678901")

	a, err := m.Encrypt(plaintext)
	if err != nil {
		t.Fatal(err)
	}
	b, err := m.Encrypt(plaintext)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Equal(a, b) {
		t.Fatal("expected distinct ciphertexts (random nonce) for repeated encryption of the same plaintext")
	}
}

func TestDecrypt_RejectsTamperedCiphertext(t *testing.T) {
	m, err := NewKeyManager(validMasterKeyHex())
	if err != nil {
		t.Fatalf("NewKeyManager: %v", err)
	}
	_, encrypted, err := m.GenerateSessionKey()
	if err != nil {
		t.Fatal(err)
	}
	tampered := append([]byte{}, encrypted...)
	tampered[len(tampered)-1] ^= 0xFF

	if _, err := m.Decrypt(tampered); err == nil {
		t.Fatal("expected decryption of tampered ciphertext to fail")
	}
}

func TestDecrypt_RejectsWrongMasterKey(t *testing.T) {
	a, err := NewKeyManager(validMasterKeyHex())
	if err != nil {
		t.Fatal(err)
	}
	b, err := NewKeyManager(strings.Repeat("cd", KeySize))
	if err != nil {
		t.Fatal(err)
	}
	_, encrypted, err := a.GenerateSessionKey()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := b.Decrypt(encrypted); err == nil {
		t.Fatal("expected decryption under a different master key to fail")
	}
}
