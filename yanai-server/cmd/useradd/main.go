// Command useradd creates (or resets the password of) one account: a users
// row, a memberships row, and — for role=teacher — a teachers row. It is
// the only way to create the first account now that yanai-server/seed/ is
// gone: no SQL file can hash a password, so this has to be Go. It creates
// only the account — the tenant must already exist, and no academic data
// (terms, competencias, classes) is created here; see SPEC.md's Open
// Questions.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"golang.org/x/term"

	"yanai-server/internal/auth"
	"yanai-server/internal/config"
	"yanai-server/internal/db"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "useradd:", err)
		os.Exit(1)
	}
}

func run() error {
	var (
		tenantFlag       = flag.String("tenant", "", "tenant UUID (must already exist); required")
		username         = flag.String("username", "", "login username; required")
		password         = flag.String("password", "", "password (omit to be prompted, hidden)")
		generatePassword = flag.Bool("generate-password", false, "mint a random password and print it once")
		email            = flag.String("email", "", "contact email; required")
		givenName        = flag.String("given-name", "", "required")
		familyName       = flag.String("family-name", "", "required")
		displayName      = flag.String("display-name", "", "defaults to \"given family\"")
		role             = flag.String("role", "teacher", "teacher|student|supervisor|admin")
		title            = flag.String("title", "Docente de Secundaria", "teachers.title")
		hiredOn          = flag.String("hired-on", "", "teachers.hired_on, YYYY-MM-DD")
		employeeCode     = flag.String("employee-code", "", "teachers.employee_code")
		noTeacherProfile = flag.Bool("no-teacher-profile", false, "skip the teachers row (for non-teacher roles)")
		resetPassword    = flag.Bool("reset-password", false, "update an existing username's password instead of creating an account")
	)
	flag.Parse()

	if *username == "" {
		return errors.New("-username is required")
	}
	uname := strings.ToLower(strings.TrimSpace(*username))

	// -tenant is only meaningful (and required) for account creation:
	// -reset-password addresses an existing account by username alone.
	var tenantID uuid.UUID
	if !*resetPassword {
		if *tenantFlag == "" {
			return errors.New("-tenant is required")
		}
		var err error
		tenantID, err = uuid.Parse(*tenantFlag)
		if err != nil {
			return fmt.Errorf("-tenant: %w", err)
		}
	}

	pw := *password
	switch {
	case *generatePassword:
		token, _, err := auth.NewSessionToken()
		if err != nil {
			return err
		}
		pw = token[:20]
		fmt.Fprintf(os.Stderr, "generated password: %s\n", pw)
	case pw == "":
		fmt.Fprint(os.Stderr, "password: ")
		b, err := term.ReadPassword(int(os.Stdin.Fd()))
		fmt.Fprintln(os.Stderr)
		if err != nil {
			return fmt.Errorf("read password: %w", err)
		}
		pw = string(b)
	}

	cfg, err := config.Load()
	if err != nil {
		return err
	}
	// This tool writes users/memberships directly (internal/db.WithSystemTx,
	// no tenant set) to seed the very first account in a tenant — that needs
	// real ownership/bypass privilege, which the app's own yanai_app
	// (DatabaseURL) does not and should not have.
	if cfg.AdminDatabaseURL == "" {
		return errors.New("ADMIN_DATABASE_URL is required (a superuser/owner connection string; useradd cannot run as the app's own yanai_app role)")
	}

	ctx := context.Background()
	database, err := db.Open(ctx, cfg.AdminDatabaseURL)
	if err != nil {
		return err
	}
	defer database.Close()

	if *resetPassword {
		return resetUserPassword(ctx, database, uname, pw, cfg.BcryptCost)
	}

	if *email == "" || *givenName == "" || *familyName == "" {
		return errors.New("-email, -given-name and -family-name are required")
	}
	if !isValidRole(*role) {
		return fmt.Errorf("-role must be one of teacher|student|supervisor|admin, got %q", *role)
	}
	dName := *displayName
	if dName == "" {
		dName = *givenName + " " + *familyName
	}

	hash, err := auth.HashPassword(pw, cfg.BcryptCost)
	if err != nil {
		return fmt.Errorf("hash password: %w", err)
	}

	var hiredOnParsed *time.Time
	if *hiredOn != "" {
		t, err := time.Parse("2006-01-02", *hiredOn)
		if err != nil {
			return fmt.Errorf("-hired-on: %w", err)
		}
		hiredOnParsed = &t
	}

	var userID, membershipID, teacherID uuid.UUID
	err = database.WithSystemTx(ctx, func(tx pgx.Tx) error {
		// The membership must exist before the users row can be read back
		// (see users' tenant_isolation policy comment in 00001), but a
		// membership references the user — so insert users, then
		// memberships, then teachers, all as the pool owner, in one
		// transaction.
		if err := tx.QueryRow(ctx, `
			insert into users (email, given_name, family_name, display_name, username, password_hash, password_changed_at)
			values (lower($1), $2, $3, $4, $5, $6, now())
			returning id
		`, *email, *givenName, *familyName, dName, uname, hash).Scan(&userID); err != nil {
			return fmt.Errorf("insert users: %w", err)
		}

		if err := tx.QueryRow(ctx, `
			insert into memberships (tenant_id, user_id, role, status, joined_at)
			values ($1, $2, $3, 'active', now())
			returning id
		`, tenantID, userID, *role).Scan(&membershipID); err != nil {
			return fmt.Errorf("insert memberships: %w", err)
		}

		if *role == "teacher" && !*noTeacherProfile {
			var employeeCodePtr, titlePtr *string
			if *employeeCode != "" {
				employeeCodePtr = employeeCode
			}
			if *title != "" {
				titlePtr = title
			}
			if err := tx.QueryRow(ctx, `
				insert into teachers (tenant_id, membership_id, employee_code, display_name, title, hired_on)
				values ($1, $2, $3, $4, $5, $6)
				returning id
			`, tenantID, membershipID, employeeCodePtr, dName, titlePtr, hiredOnParsed).Scan(&teacherID); err != nil {
				return fmt.Errorf("insert teachers: %w", err)
			}
		}
		return nil
	})
	if err != nil {
		return friendlyPGError(err)
	}

	fmt.Printf("user_id=%s\n", userID)
	fmt.Printf("membership_id=%s\n", membershipID)
	if teacherID != uuid.Nil {
		fmt.Printf("teacher_id=%s\n", teacherID)
	}
	return nil
}

func resetUserPassword(ctx context.Context, database *db.DB, username, password string, cost int) error {
	hash, err := auth.HashPassword(password, cost)
	if err != nil {
		return fmt.Errorf("hash password: %w", err)
	}
	var userID uuid.UUID
	err = database.WithSystemTx(ctx, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx, `
			update users
			   set password_hash = $2, password_changed_at = now(),
			       failed_login_count = 0, locked_until = null
			 where lower(username) = lower($1) and deleted_at is null
			returning id
		`, username, hash).Scan(&userID)
	})
	if err == pgx.ErrNoRows {
		return fmt.Errorf("no user with username %q", username)
	}
	if err != nil {
		return friendlyPGError(err)
	}
	// Revoking every live session for the user on a password change is the
	// same policy internal/repo/auth.go documents for a self-service change.
	err = database.WithSystemTx(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `
			update user_sessions set revoked_at = now(), revoked_reason = 'password_change'
			 where user_id = $1 and revoked_at is null
		`, userID)
		return err
	})
	if err != nil {
		return err
	}
	fmt.Printf("user_id=%s password reset\n", userID)
	return nil
}

func isValidRole(role string) bool {
	switch role {
	case "teacher", "student", "supervisor", "admin":
		return true
	default:
		return false
	}
}

func friendlyPGError(err error) error {
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) {
		switch pgErr.ConstraintName {
		case "users_username_key":
			return errors.New("that username is already taken")
		case "users_email_key":
			return errors.New("that email is already registered")
		case "memberships_one_school_per_user":
			return errors.New("this user already has an active membership at a school — a person may belong to only one")
		}
		return fmt.Errorf("%s: %s", pgErr.Code, pgErr.Message)
	}
	return err
}
