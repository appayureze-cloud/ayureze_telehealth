package e2ee

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"
)

// fakeVault is a minimal in-process stand-in for the subset of Vault's
// HTTP API VaultMasterKeyProvider calls: Kubernetes-auth login and
// Transit encrypt/decrypt. It stores "ciphertext" as a reversible,
// deterministic transform (not real crypto) purely so round-trips can be
// asserted — the real provider never interprets Vault's ciphertext
// format itself, so a fake encoding is sufficient to test the HTTP
// plumbing (auth header, retry-on-403, request/response shapes).
type fakeVault struct {
	server      *httptest.Server
	loginCalls  atomic.Int64
	validToken  string
	expireAfter atomic.Int64 // number of authenticated calls after which the token is rejected once
	rejectOnce  atomic.Bool
}

func newFakeVault(t *testing.T) *fakeVault {
	t.Helper()
	fv := &fakeVault{validToken: "s.fake-token-initial"}
	mux := http.NewServeMux()

	mux.HandleFunc("/v1/auth/kubernetes/login", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Role string `json:"role"`
			JWT  string `json:"jwt"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		if body.Role != "ayureze-api" || body.JWT == "" {
			http.Error(w, "bad role/jwt", http.StatusBadRequest)
			return
		}
		n := fv.loginCalls.Add(1)
		token := fmt.Sprintf("%s-%d", fv.validToken, n)
		fv.validToken = token
		fv.rejectOnce.Store(false)
		_ = json.NewEncoder(w).Encode(map[string]any{
			"auth": map[string]any{
				"client_token":   token,
				"lease_duration": 3600,
			},
		})
	})

	mux.HandleFunc("/v1/transit/encrypt/ayureze-e2ee-master", func(w http.ResponseWriter, r *http.Request) {
		if !fv.authorize(w, r) {
			return
		}
		var body struct {
			Plaintext string `json:"plaintext"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		ciphertext := "vault:v1:" + body.Plaintext // fake wrapping, reversible below
		_ = json.NewEncoder(w).Encode(map[string]any{
			"data": map[string]any{"ciphertext": ciphertext},
		})
	})

	mux.HandleFunc("/v1/transit/decrypt/ayureze-e2ee-master", func(w http.ResponseWriter, r *http.Request) {
		if !fv.authorize(w, r) {
			return
		}
		var body struct {
			Ciphertext string `json:"ciphertext"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		const prefix = "vault:v1:"
		if len(body.Ciphertext) < len(prefix) {
			http.Error(w, "bad ciphertext", http.StatusBadRequest)
			return
		}
		plaintext := body.Ciphertext[len(prefix):]
		_ = json.NewEncoder(w).Encode(map[string]any{
			"data": map[string]any{"plaintext": plaintext},
		})
	})

	fv.server = httptest.NewServer(mux)
	t.Cleanup(fv.server.Close)
	return fv
}

func (fv *fakeVault) authorize(w http.ResponseWriter, r *http.Request) bool {
	if fv.rejectOnce.Load() {
		fv.rejectOnce.Store(false)
		http.Error(w, "permission denied", http.StatusForbidden)
		return false
	}
	token := r.Header.Get("X-Vault-Token")
	if token == "" || token != fv.validToken {
		http.Error(w, "permission denied", http.StatusForbidden)
		return false
	}
	return true
}

func fakeServiceAccountToken(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "token")
	if err := os.WriteFile(path, []byte("fake-jwt-contents"), 0o600); err != nil {
		t.Fatalf("write fake service account token: %v", err)
	}
	return path
}

func newTestProvider(t *testing.T, fv *fakeVault) *VaultMasterKeyProvider {
	t.Helper()
	p, err := NewVaultMasterKeyProvider(VaultProviderConfig{
		Addr:                    fv.server.URL,
		TransitKeyName:          "ayureze-e2ee-master",
		K8sRole:                 "ayureze-api",
		ServiceAccountTokenPath: fakeServiceAccountToken(t),
		HTTPClient:              &http.Client{Timeout: 5 * time.Second},
	})
	if err != nil {
		t.Fatalf("NewVaultMasterKeyProvider: %v", err)
	}
	return p
}

func TestVaultMasterKeyProvider_LoginsOnConstruction(t *testing.T) {
	fv := newFakeVault(t)
	newTestProvider(t, fv)
	if got := fv.loginCalls.Load(); got != 1 {
		t.Fatalf("expected exactly 1 login call during construction, got %d", got)
	}
}

func TestVaultMasterKeyProvider_EncryptDecryptRoundTrip(t *testing.T) {
	fv := newFakeVault(t)
	p := newTestProvider(t, fv)

	plaintext := []byte("super-secret-session-key-bytes!")
	encrypted, err := p.Encrypt(plaintext)
	if err != nil {
		t.Fatalf("Encrypt: %v", err)
	}
	if string(encrypted) == string(plaintext) {
		t.Fatal("encrypted output must not equal the plaintext")
	}

	decrypted, err := p.Decrypt(encrypted)
	if err != nil {
		t.Fatalf("Decrypt: %v", err)
	}
	if string(decrypted) != string(plaintext) {
		t.Fatalf("round trip mismatch: got %q, want %q", decrypted, plaintext)
	}
}

func TestVaultMasterKeyProvider_RetriesOnceAfter403(t *testing.T) {
	fv := newFakeVault(t)
	p := newTestProvider(t, fv)

	fv.rejectOnce.Store(true) // simulate an expired/revoked token on the next call

	plaintext := []byte("retry-me")
	encrypted, err := p.Encrypt(plaintext)
	if err != nil {
		t.Fatalf("Encrypt should transparently re-login and succeed, got error: %v", err)
	}
	decrypted, err := p.Decrypt(encrypted)
	if err != nil {
		t.Fatalf("Decrypt: %v", err)
	}
	if string(decrypted) != string(plaintext) {
		t.Fatalf("round trip mismatch after retry: got %q, want %q", decrypted, plaintext)
	}
	if got := fv.loginCalls.Load(); got != 2 {
		t.Fatalf("expected 2 login calls (initial + retry-triggered), got %d", got)
	}
}

func TestVaultMasterKeyProvider_ConstructorValidatesConfig(t *testing.T) {
	cases := []struct {
		name string
		cfg  VaultProviderConfig
		want error
	}{
		{"missing addr", VaultProviderConfig{TransitKeyName: "k", K8sRole: "r"}, ErrVaultAddrRequired},
		{"missing transit key", VaultProviderConfig{Addr: "http://x", K8sRole: "r"}, ErrVaultTransitKeyEmpty},
		{"missing k8s role", VaultProviderConfig{Addr: "http://x", TransitKeyName: "k"}, ErrVaultK8sRoleRequired},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := NewVaultMasterKeyProvider(tc.cfg); err != tc.want {
				t.Fatalf("expected %v, got %v", tc.want, err)
			}
		})
	}
}

func TestVaultMasterKeyProvider_CiphertextIsBase64SafeWireFormat(t *testing.T) {
	// Sanity check that ciphertext round-trips even when the plaintext
	// contains bytes that would need base64 encoding (not printable
	// ASCII), proving Encrypt/Decrypt correctly base64-encode/decode at
	// the Vault API boundary rather than passing raw bytes through.
	fv := newFakeVault(t)
	p := newTestProvider(t, fv)

	plaintext := make([]byte, KeySize)
	for i := range plaintext {
		plaintext[i] = byte(i)
	}
	encrypted, err := p.Encrypt(plaintext)
	if err != nil {
		t.Fatalf("Encrypt: %v", err)
	}
	// The fake server stores whatever Encrypt sent as the base64 of
	// plaintext — confirm it actually is valid base64.
	const prefix = "vault:v1:"
	if _, err := base64.StdEncoding.DecodeString(string(encrypted)[len(prefix):]); err != nil {
		t.Fatalf("expected base64-encoded plaintext in ciphertext payload: %v", err)
	}

	decrypted, err := p.Decrypt(encrypted)
	if err != nil {
		t.Fatalf("Decrypt: %v", err)
	}
	if string(decrypted) != string(plaintext) {
		t.Fatal("round trip mismatch for binary plaintext")
	}
}
