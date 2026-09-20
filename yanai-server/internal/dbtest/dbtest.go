// Package dbtest stands up a throwaway PostgreSQL database for the tests that
// need a real one: create, migrate with the project's own goose migration,
// seed deterministic fixtures, drop.
//
// Read SPEC.md before changing anything here. Two rules in it are load-bearing
// and not obvious from the code: the migration has to run as the superuser in
// a single goose invocation against an empty database (00001's ALTER DEFAULT
// PRIVILEGES only reaches tables created afterwards by that same role), and
// tests have to run against the yanai_app pool rather than the admin one, or a
// missing GRANT passes unnoticed.
//
// This package is test-only. Nothing outside a _test.go file imports it.
package dbtest

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/stdlib"
	"github.com/pressly/goose/v3"

	"yanai-server/internal/db"
)

// AdminURLEnv is the only environment variable this package reads. It is
// deliberately not DATABASE_URL: pointing the tests at whatever the developer
// happens to have configured is how a test suite eats a dev database.
const AdminURLEnv = "YANAI_TEST_ADMIN_URL"

// KeepEnv retains the database after the run instead of dropping it.
const KeepEnv = "YANAI_TEST_KEEP"

// appPassword is set on yanai_app so the app pool can connect. The role is
// created passwordless by 00001 and is cluster-wide, so this is once per
// cluster rather than once per database.
const appPassword = "yanai_app_test"

// testDBName guards every drop. Nothing that does not match this shape is ever
// passed to `drop database`.
var testDBName = regexp.MustCompile(`^yanai_test_[0-9a-f]{12}$`)

// Env is what a test gets: two pools and the fixture ids.
type Env struct {
	// App is connected as the non-owner yanai_app role — the same role
	// cmd/api runs as. Code under test uses this one.
	App *db.DB
	// Admin is the superuser pool. Use it to seed, and to assert on rows that
	// RLS would otherwise hide. Never use it to exercise the code under test.
	Admin *db.DB
	// Fx names the rows fixture.sql created.
	Fx Fixture
}

// shared is the per-binary state. The database is created once and reused by
// every test in the package, because migrating 2,900 lines of schema per test
// would dominate the runtime.
var shared struct {
	env     *Env
	dbName  string
	skip    string // non-empty means every Setup call skips, with this reason
	adminDB string
}

// Main creates the database, runs the package's tests against it, and drops it.
// Each test package that needs a database calls it from TestMain:
//
//	func TestMain(m *testing.M) { os.Exit(dbtest.Main(m)) }
//
// With YANAI_TEST_ADMIN_URL unset it still runs the package — the tests that
// need a database skip themselves through Setup, and any pure tests in the
// same package keep running.
func Main(m *testing.M) int {
	adminURL := strings.TrimSpace(os.Getenv(AdminURLEnv))
	if adminURL == "" {
		shared.skip = AdminURLEnv + " is not set, so there is no database to test against.\n" +
			"    Start one and point this at it, e.g.:\n" +
			"    export " + AdminURLEnv + "='postgres://postgres:yanai@localhost:55432/postgres?sslmode=disable'"
		// Say it on stderr as well as in each skip. Note `go test` swallows a
		// passing package's output unless -v, so this banner is visible under
		// `go test -v` and in CI logs, not in a bare `go test ./...`. That is
		// why CI always sets the variable: a false baseline must be impossible
		// to merge, whatever a local run happens to print.
		fmt.Fprintf(os.Stderr,
			"\n  ⚠  DATABASE TESTS SKIPPED — %s is not set.\n"+
				"     This run proved nothing about the database.\n"+
				"     export %s='postgres://postgres:yanai@localhost:55432/postgres?sslmode=disable'\n\n",
			AdminURLEnv, AdminURLEnv)
		return m.Run()
	}

	if err := provision(adminURL); err != nil {
		// Failing to provision is not a skip. A configured-but-broken database
		// must stop the run, or the suite reports success having tested nothing.
		fmt.Fprintf(os.Stderr, "dbtest: %v\n", err)
		// The database may already exist — provision fails at the migration or
		// the fixture just as often as at creation — so tear down regardless
		// rather than leaving it behind on every failed run.
		if err := teardown(); err != nil {
			fmt.Fprintf(os.Stderr, "dbtest: teardown after a failed provision: %v\n", err)
		}
		return 1
	}

	code := m.Run()

	if os.Getenv(KeepEnv) == "1" {
		fmt.Fprintf(os.Stderr, "dbtest: %s=1, keeping database %s\n", KeepEnv, shared.dbName)
	} else if err := teardown(); err != nil {
		fmt.Fprintf(os.Stderr, "dbtest: teardown: %v\n", err)
		if code == 0 {
			code = 1
		}
	}
	if shared.env != nil {
		shared.env.App.Close()
		shared.env.Admin.Close()
	}
	return code
}

// Setup returns the shared environment, or skips the test when there is no
// database. The skip names the missing variable: a database test that quietly
// reports ok is the false baseline this whole package exists to prevent.
func Setup(t *testing.T) *Env {
	t.Helper()
	if shared.skip != "" {
		t.Skip("dbtest: " + shared.skip)
	}
	if shared.env == nil {
		t.Fatal("dbtest: Setup called without Main — add `func TestMain(m *testing.M) { os.Exit(dbtest.Main(m)) }` to this package")
	}
	return shared.env
}

func provision(adminURL string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	name, err := newDBName()
	if err != nil {
		return err
	}

	maintenance, err := pgx.Connect(ctx, adminURL)
	if err != nil {
		return fmt.Errorf("connect to %s: %w", AdminURLEnv, err)
	}
	// CREATE DATABASE cannot be parameterised, hence the identifier quoting;
	// the name is one this package minted, not anything from outside.
	if _, err := maintenance.Exec(ctx, `create database `+quoteIdent(name)); err != nil {
		maintenance.Close(ctx)
		return fmt.Errorf("create database %s: %w", name, err)
	}
	maintenance.Close(ctx)

	shared.dbName = name
	shared.adminDB = adminURL

	adminOnNew := replaceDatabase(adminURL, name)

	if err := migrate(ctx, adminOnNew); err != nil {
		return err
	}

	admin, err := db.Open(ctx, adminOnNew)
	if err != nil {
		return fmt.Errorf("open admin pool: %w", err)
	}

	// 00001 creates yanai_app with login and no password. Without this the
	// app pool below cannot connect at all.
	if _, err := admin.Pool.Exec(ctx, `alter role yanai_app login password `+quoteLiteral(appPassword)); err != nil {
		admin.Close()
		return fmt.Errorf("set yanai_app password: %w", err)
	}

	fx, err := seed(ctx, admin)
	if err != nil {
		admin.Close()
		return fmt.Errorf("seed fixtures: %w", err)
	}

	app, err := db.Open(ctx, appURL(adminOnNew, name))
	if err != nil {
		admin.Close()
		return fmt.Errorf("open yanai_app pool (check the GRANTs in 00001): %w", err)
	}

	shared.env = &Env{App: app, Admin: admin, Fx: fx}
	return nil
}

// migrate runs the project's real migration, as the superuser, in one goose
// invocation. See SPEC.md for why all three of those matter.
func migrate(ctx context.Context, url string) error {
	sqlDB := stdlib.OpenDB(*mustParseConfig(url))
	defer sqlDB.Close()

	goose.SetLogger(goose.NopLogger())
	if err := goose.SetDialect("postgres"); err != nil {
		return fmt.Errorf("goose dialect: %w", err)
	}

	dir, err := migrationsDir()
	if err != nil {
		return err
	}
	if err := goose.UpContext(ctx, sqlDB, dir); err != nil {
		return fmt.Errorf("goose up: %w", err)
	}
	return nil
}

func teardown() error {
	if shared.dbName == "" {
		return nil
	}
	// Belt and braces: this is the only drop in the package, and it refuses
	// anything that is not a name this package generated.
	if !testDBName.MatchString(shared.dbName) {
		return fmt.Errorf("refusing to drop %q: not a dbtest-generated database", shared.dbName)
	}

	if shared.env != nil {
		shared.env.App.Close()
		shared.env.Admin.Close()
		shared.env = nil
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	conn, err := pgx.Connect(ctx, shared.adminDB)
	if err != nil {
		return fmt.Errorf("connect for teardown: %w", err)
	}
	defer conn.Close(ctx)

	if _, err := conn.Exec(ctx, `drop database if exists `+quoteIdent(shared.dbName)+` with (force)`); err != nil {
		return fmt.Errorf("drop database %s: %w", shared.dbName, err)
	}
	shared.dbName = ""
	return nil
}

func newDBName() (string, error) {
	buf := make([]byte, 6)
	if _, err := rand.Read(buf); err != nil {
		return "", fmt.Errorf("generate database name: %w", err)
	}
	name := "yanai_test_" + hex.EncodeToString(buf)
	if !testDBName.MatchString(name) {
		return "", fmt.Errorf("generated name %q does not match the expected shape", name)
	}
	return name, nil
}

func mustParseConfig(url string) *pgx.ConnConfig {
	cfg, err := pgx.ParseConfig(url)
	if err != nil {
		panic(fmt.Sprintf("dbtest: parse connection string: %v", err))
	}
	return cfg
}

// replaceDatabase points a connection string at a different database, keeping
// host, credentials and parameters.
func replaceDatabase(url, name string) string {
	cfg := mustParseConfig(url)
	cfg.Database = name
	return renderURL(cfg.User, cfg.Password, cfg.Host, int(cfg.Port), name, sslMode(url))
}

// appURL is the same host and database as the admin connection, but as the
// non-owner yanai_app role.
func appURL(url, name string) string {
	cfg := mustParseConfig(url)
	return renderURL("yanai_app", appPassword, cfg.Host, int(cfg.Port), name, sslMode(url))
}

func renderURL(user, password, host string, port int, database, ssl string) string {
	return fmt.Sprintf("postgres://%s:%s@%s:%d/%s?sslmode=%s", user, password, host, port, database, ssl)
}

func sslMode(url string) string {
	if strings.Contains(url, "sslmode=") {
		rest := url[strings.Index(url, "sslmode=")+len("sslmode="):]
		if i := strings.IndexAny(rest, "&"); i >= 0 {
			rest = rest[:i]
		}
		return rest
	}
	return "disable"
}

func quoteIdent(s string) string   { return `"` + strings.ReplaceAll(s, `"`, `""`) + `"` }
func quoteLiteral(s string) string { return `'` + strings.ReplaceAll(s, `'`, `''`) + `'` }
