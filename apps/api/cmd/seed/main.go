// Command seed inserts local-development-only tenant/user data so the
// login flow (internal/authsvc) has something to authenticate against.
// Real user provisioning is a future integration with the main AyurEze
// platform — this command exists purely for local dev and the Day 3 test
// suite. It refuses to run when ENVIRONMENT=production.
package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"

	"github.com/ayureze/telehealth/api/internal/authn"
	"github.com/ayureze/telehealth/api/internal/db"
	"github.com/ayureze/telehealth/api/internal/domain"
	"github.com/ayureze/telehealth/api/internal/store"
)

func main() {
	if os.Getenv("ENVIRONMENT") == "production" {
		fmt.Fprintln(os.Stderr, "refusing to run the dev seed command with ENVIRONMENT=production")
		os.Exit(1)
	}

	databaseURL := os.Getenv("DATABASE_URL")
	if databaseURL == "" {
		fmt.Fprintln(os.Stderr, "DATABASE_URL is required")
		os.Exit(1)
	}

	ctx := context.Background()
	if err := db.Migrate(databaseURL); err != nil {
		slog.Error("migrate_failed", slog.String("error", err.Error()))
		os.Exit(1)
	}
	pool, err := db.NewPool(ctx, databaseURL)
	if err != nil {
		slog.Error("db_connect_failed", slog.String("error", err.Error()))
		os.Exit(1)
	}
	defer pool.Close()

	tenantName := envDefault("SEED_TENANT_NAME", "ayureze-dev")
	doctorEmail := envDefault("SEED_DOCTOR_EMAIL", "doctor@ayureze.test")
	patientEmail := envDefault("SEED_PATIENT_EMAIL", "patient@ayureze.test")
	password := envDefault("SEED_PASSWORD", "dev-password-only-12345")

	tenants := store.NewTenantStore(pool)
	users := store.NewUserStore(pool)

	tenant, err := tenants.EnsureByName(ctx, tenantName)
	if err != nil {
		slog.Error("ensure_tenant_failed", slog.String("error", err.Error()))
		os.Exit(1)
	}

	hash, err := authn.HashPassword(password)
	if err != nil {
		slog.Error("hash_password_failed", slog.String("error", err.Error()))
		os.Exit(1)
	}

	doctor, err := users.Create(ctx, domain.User{
		TenantID: tenant.ID, Email: doctorEmail, PasswordHash: hash, Role: domain.RoleDoctor, DisplayName: "Dr. Dev Test",
	})
	if err != nil {
		slog.Error("create_doctor_failed", slog.String("error", err.Error()))
		os.Exit(1)
	}

	patient, err := users.Create(ctx, domain.User{
		TenantID: tenant.ID, Email: patientEmail, PasswordHash: hash, Role: domain.RolePatient, DisplayName: "Patient Dev Test",
	})
	if err != nil {
		slog.Error("create_patient_failed", slog.String("error", err.Error()))
		os.Exit(1)
	}

	fmt.Printf("Seeded tenant %q (%s)\n", tenant.Name, tenant.ID)
	fmt.Printf("  doctor:  %s / %s (id=%s)\n", doctor.Email, password, doctor.ID)
	fmt.Printf("  patient: %s / %s (id=%s)\n", patient.Email, password, patient.ID)
}

func envDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
