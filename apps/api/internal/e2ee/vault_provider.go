package e2ee

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

// VaultMasterKeyProvider implements MasterKeyProvider against HashiCorp
// Vault's Transit secrets engine, as the package doc comment on
// MasterKeyProvider calls for in production: the master key itself never
// leaves Vault and is never held in this process's memory. Every
// Encrypt/Decrypt call is a real round trip to Vault's
// /v1/transit/{encrypt,decrypt}/<key> endpoints — this process only ever
// sees ciphertext (the ciphertext returned here is Vault's own
// "vault:v1:base64..." wire format, stored as opaque bytes by callers) and,
// transiently, the plaintext Decrypt returns to its authorized caller.
//
// Authentication uses Vault's Kubernetes auth method (a direct API call,
// not the Vault Agent Injector sidecar pattern): the pod's projected
// ServiceAccount token is exchanged for a short-lived Vault token via
// POST /v1/auth/kubernetes/login, which this provider transparently
// re-does whenever its current token is at or near expiry. This keeps the
// API server binary self-contained — no sidecar/init-container coordination
// required beyond the ServiceAccount token k8s already projects into every
// pod — consistent with the distroless, dependency-minimal container this
// repo already ships (apps/api/Dockerfile).
type VaultMasterKeyProvider struct {
	addr       string
	transitKey string
	httpClient *http.Client

	k8sRole      string
	k8sLoginPath string
	k8sJWTPath   string

	authMu     sync.Mutex
	token      string
	tokenExpAt time.Time
}

// VaultProviderConfig holds the settings needed to construct a
// VaultMasterKeyProvider. Addr, TransitKeyName and K8sRole are required;
// the rest have production-sane defaults matching Vault's and Kubernetes'
// own conventions.
type VaultProviderConfig struct {
	// Addr is Vault's base URL, e.g. "https://vault.internal:8200".
	Addr string
	// TransitKeyName is the name of the Transit engine key to
	// encrypt/decrypt under, e.g. "ayureze-e2ee-master".
	TransitKeyName string
	// K8sRole is the Vault Kubernetes auth role bound to this
	// deployment's ServiceAccount.
	K8sRole string
	// K8sLoginPath is the Vault auth mount path for the login call.
	// Defaults to "auth/kubernetes/login".
	K8sLoginPath string
	// ServiceAccountTokenPath is where the pod's projected ServiceAccount
	// JWT is mounted. Defaults to
	// "/var/run/secrets/kubernetes.io/serviceaccount/token" (the
	// standard k8s projection path).
	ServiceAccountTokenPath string
	// HTTPClient is optional; a 10s-timeout client is used if nil.
	HTTPClient *http.Client
}

var (
	ErrVaultAddrRequired    = errors.New("vault addr is required")
	ErrVaultTransitKeyEmpty = errors.New("vault transit key name is required")
	ErrVaultK8sRoleRequired = errors.New("vault k8s role is required")
)

// NewVaultMasterKeyProvider constructs a VaultMasterKeyProvider and
// performs an initial Kubernetes-auth login against Vault, so
// construction fails fast (at process startup, alongside every other
// required-config check in internal/config) rather than on the first real
// Encrypt/Decrypt call.
func NewVaultMasterKeyProvider(cfg VaultProviderConfig) (*VaultMasterKeyProvider, error) {
	if cfg.Addr == "" {
		return nil, ErrVaultAddrRequired
	}
	if cfg.TransitKeyName == "" {
		return nil, ErrVaultTransitKeyEmpty
	}
	if cfg.K8sRole == "" {
		return nil, ErrVaultK8sRoleRequired
	}
	loginPath := cfg.K8sLoginPath
	if loginPath == "" {
		loginPath = "auth/kubernetes/login"
	}
	jwtPath := cfg.ServiceAccountTokenPath
	if jwtPath == "" {
		jwtPath = "/var/run/secrets/kubernetes.io/serviceaccount/token"
	}
	httpClient := cfg.HTTPClient
	if httpClient == nil {
		httpClient = &http.Client{Timeout: 10 * time.Second}
	}

	p := &VaultMasterKeyProvider{
		addr:         strings.TrimRight(cfg.Addr, "/"),
		transitKey:   cfg.TransitKeyName,
		httpClient:   httpClient,
		k8sRole:      cfg.K8sRole,
		k8sLoginPath: strings.Trim(loginPath, "/"),
		k8sJWTPath:   jwtPath,
	}

	ctx, cancel := context.WithTimeout(context.Background(), httpClient.Timeout)
	defer cancel()
	if _, err := p.login(ctx); err != nil {
		return nil, fmt.Errorf("vault kubernetes auth login: %w", err)
	}
	return p, nil
}

func (p *VaultMasterKeyProvider) Encrypt(plaintext []byte) ([]byte, error) {
	ctx, cancel := context.WithTimeout(context.Background(), p.httpClient.Timeout)
	defer cancel()

	path := fmt.Sprintf("v1/transit/encrypt/%s", p.transitKey)
	reqBody := map[string]string{"plaintext": base64.StdEncoding.EncodeToString(plaintext)}

	var result struct {
		Data struct {
			Ciphertext string `json:"ciphertext"`
		} `json:"data"`
	}
	if err := p.doTransitCall(ctx, path, reqBody, &result); err != nil {
		return nil, fmt.Errorf("vault transit encrypt: %w", err)
	}
	if result.Data.Ciphertext == "" {
		return nil, errors.New("vault transit encrypt: empty ciphertext in response")
	}
	// Vault's own "vault:v1:base64..." wire format is stored verbatim as
	// opaque bytes — callers (KeyManager, internal/sessionsvc) never
	// parse or interpret it, only round-trip it back into Decrypt.
	return []byte(result.Data.Ciphertext), nil
}

func (p *VaultMasterKeyProvider) Decrypt(encrypted []byte) ([]byte, error) {
	ctx, cancel := context.WithTimeout(context.Background(), p.httpClient.Timeout)
	defer cancel()

	path := fmt.Sprintf("v1/transit/decrypt/%s", p.transitKey)
	reqBody := map[string]string{"ciphertext": string(encrypted)}

	var result struct {
		Data struct {
			Plaintext string `json:"plaintext"`
		} `json:"data"`
	}
	if err := p.doTransitCall(ctx, path, reqBody, &result); err != nil {
		return nil, fmt.Errorf("vault transit decrypt: %w", err)
	}
	plaintext, err := base64.StdEncoding.DecodeString(result.Data.Plaintext)
	if err != nil {
		return nil, fmt.Errorf("vault transit decrypt: invalid base64 plaintext: %w", err)
	}
	return plaintext, nil
}

// doTransitCall issues one authenticated Transit API call, retrying
// exactly once after a fresh login if Vault reports the token as invalid
// (403) — covering both normal lease expiry and a token revoked out of
// band, without masking any other failure behind a retry loop.
func (p *VaultMasterKeyProvider) doTransitCall(ctx context.Context, path string, reqBody any, out any) error {
	token, err := p.currentToken(ctx)
	if err != nil {
		return err
	}
	status, err := p.callVault(ctx, token, path, reqBody, out)
	if err == nil {
		return nil
	}
	if status != http.StatusForbidden {
		return err
	}

	token, loginErr := p.login(ctx)
	if loginErr != nil {
		return fmt.Errorf("token rejected (403) and re-login failed: %w", loginErr)
	}
	if _, err := p.callVault(ctx, token, path, reqBody, out); err != nil {
		return err
	}
	return nil
}

func (p *VaultMasterKeyProvider) callVault(ctx context.Context, token, path string, reqBody any, out any) (int, error) {
	body, err := json.Marshal(reqBody)
	if err != nil {
		return 0, fmt.Errorf("encode request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, p.addr+"/"+path, bytes.NewReader(body))
	if err != nil {
		return 0, fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Vault-Token", token)

	resp, err := p.httpClient.Do(req)
	if err != nil {
		return 0, fmt.Errorf("vault request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return resp.StatusCode, fmt.Errorf("read vault response: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return resp.StatusCode, fmt.Errorf("vault returned %d: %s", resp.StatusCode, truncate(respBody, 500))
	}
	if err := json.Unmarshal(respBody, out); err != nil {
		return resp.StatusCode, fmt.Errorf("decode vault response: %w", err)
	}
	return resp.StatusCode, nil
}

// currentToken returns the cached Vault token, transparently re-logging-in
// if it is absent or within 30s of its lease expiry.
func (p *VaultMasterKeyProvider) currentToken(ctx context.Context) (string, error) {
	p.authMu.Lock()
	token, expAt := p.token, p.tokenExpAt
	p.authMu.Unlock()

	if token != "" && time.Now().Add(30*time.Second).Before(expAt) {
		return token, nil
	}
	return p.login(ctx)
}

// login exchanges the pod's projected ServiceAccount JWT for a Vault
// token via the Kubernetes auth method and caches it.
func (p *VaultMasterKeyProvider) login(ctx context.Context) (string, error) {
	jwt, err := os.ReadFile(p.k8sJWTPath)
	if err != nil {
		return "", fmt.Errorf("read service account token at %s: %w", p.k8sJWTPath, err)
	}

	reqBody := map[string]string{
		"role": p.k8sRole,
		"jwt":  strings.TrimSpace(string(jwt)),
	}
	body, err := json.Marshal(reqBody)
	if err != nil {
		return "", fmt.Errorf("encode login request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, p.addr+"/v1/"+p.k8sLoginPath, bytes.NewReader(body))
	if err != nil {
		return "", fmt.Errorf("build login request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := p.httpClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("vault login request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("read vault login response: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("vault login returned %d: %s", resp.StatusCode, truncate(respBody, 500))
	}

	var loginResp struct {
		Auth struct {
			ClientToken   string `json:"client_token"`
			LeaseDuration int    `json:"lease_duration"`
		} `json:"auth"`
	}
	if err := json.Unmarshal(respBody, &loginResp); err != nil {
		return "", fmt.Errorf("decode vault login response: %w", err)
	}
	if loginResp.Auth.ClientToken == "" {
		return "", errors.New("vault login response had no client_token")
	}

	p.authMu.Lock()
	p.token = loginResp.Auth.ClientToken
	p.tokenExpAt = time.Now().Add(time.Duration(loginResp.Auth.LeaseDuration) * time.Second)
	p.authMu.Unlock()

	return loginResp.Auth.ClientToken, nil
}

func truncate(b []byte, n int) string {
	s := string(b)
	if len(s) <= n {
		return s
	}
	return s[:n] + "...(truncated)"
}
