package db_test

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"mawta-server/internal/dbtest"
)

// The chat service connects as mawta_chat. These tests take that role with
// SET LOCAL ROLE on the admin pool, the way the chat service will set
// app.tenant_id and app.actor_id per transaction.

func asChat(t *testing.T, env *dbtest.Env, tenantID, actorID uuid.UUID, fn func(tx pgx.Tx) error) error {
	t.Helper()
	ctx := context.Background()
	tx, err := env.Admin.Pool.Begin(ctx)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	defer tx.Rollback(ctx) //nolint:errcheck
	if _, err := tx.Exec(ctx, `set local role mawta_chat`); err != nil {
		t.Fatalf("set role: %v", err)
	}
	if tenantID != uuid.Nil {
		if _, err := tx.Exec(ctx, `select set_config('app.tenant_id', $1, true), set_config('app.actor_id', $2, true)`,
			tenantID.String(), actorID.String()); err != nil {
			t.Fatalf("set the session: %v", err)
		}
	}
	if err := fn(tx); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func pgCode(err error) string {
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) {
		return pgErr.Code
	}
	return ""
}

const insufficientPrivilege = "42501"

func TestChatViewsSeeOnlyTheSessionSchool(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()

	var wantSections int
	if err := env.Admin.Pool.QueryRow(ctx,
		`select count(*) from sections where tenant_id = $1 and deleted_at is null`, env.Fx.TenantA).Scan(&wantSections); err != nil {
		t.Fatalf("count sections: %v", err)
	}
	if wantSections == 0 {
		t.Fatal("the fixture has no sections in tenant A")
	}

	err := asChat(t, env, env.Fx.TenantA, env.Fx.UserQuispe, func(tx pgx.Tx) error {
		var schoolID uuid.UUID
		var schools, sections int
		if err := tx.QueryRow(ctx, `select count(*), min(id::text)::uuid from chat_api.school`).Scan(&schools, &schoolID); err != nil {
			return err
		}
		if schools != 1 || schoolID != env.Fx.TenantA {
			t.Errorf("chat_api.school: %d rows, id %s; want 1 row, tenant A", schools, schoolID)
		}
		if err := tx.QueryRow(ctx, `select count(*) from chat_api.sections`).Scan(&sections); err != nil {
			return err
		}
		if sections != wantSections {
			t.Errorf("chat_api.sections: %d rows, want %d (tenant A only)", sections, wantSections)
		}
		return nil
	})
	if err != nil {
		t.Fatalf("as chat, tenant A: %v", err)
	}

	err = asChat(t, env, uuid.Nil, uuid.Nil, func(tx pgx.Tx) error {
		var schools, sections int
		if err := tx.QueryRow(ctx, `select (select count(*) from chat_api.school), (select count(*) from chat_api.sections)`).Scan(&schools, &sections); err != nil {
			return err
		}
		if schools != 0 || sections != 0 {
			t.Errorf("without app.tenant_id: %d schools, %d sections; want none", schools, sections)
		}
		return nil
	})
	if err != nil {
		t.Fatalf("as chat, no tenant: %v", err)
	}
}

func TestChatCannotReadMawtaTables(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	for _, table := range []string{"students", "sections", "tenants", "users"} {
		err := asChat(t, env, env.Fx.TenantA, env.Fx.UserQuispe, func(tx pgx.Tx) error {
			_, err := tx.Exec(ctx, `select 1 from public.`+table+` limit 1`)
			return err
		})
		if pgCode(err) != insufficientPrivilege {
			t.Errorf("reading public.%s as mawta_chat: err = %v, want permission denied", table, err)
		}
	}
}

func TestChatThreadsBelongToOneSchoolAndOneUser(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	t.Cleanup(func() {
		env.Admin.Pool.Exec(context.Background(), `delete from chat.threads where tenant_id in ($1, $2)`, env.Fx.TenantA, env.Fx.TenantB) //nolint:errcheck
	})

	var threadID uuid.UUID
	err := asChat(t, env, env.Fx.TenantA, env.Fx.UserQuispe, func(tx pgx.Tx) error {
		if err := tx.QueryRow(ctx,
			`insert into chat.threads (tenant_id, user_id, title) values ($1, $2, 'Avance de evidencias') returning id`,
			env.Fx.TenantA, env.Fx.UserQuispe).Scan(&threadID); err != nil {
			return err
		}
		var messageID uuid.UUID
		if err := tx.QueryRow(ctx, `
			insert into chat.messages (tenant_id, thread_id, user_id, author, blocks)
			values ($1, $2, $3, 'director', '[{"tipo":"texto","md":"¿Qué secciones van atrasadas?"}]') returning id`,
			env.Fx.TenantA, threadID, env.Fx.UserQuispe).Scan(&messageID); err != nil {
			return err
		}
		_, err := tx.Exec(ctx, `
			insert into chat.question_bank (tenant_id, message_id, question, status)
			values ($1, $2, '¿Qué secciones van atrasadas?', 'necesita_tool')`, env.Fx.TenantA, messageID)
		return err
	})
	if err != nil {
		t.Fatalf("the owner writes a thread: %v", err)
	}

	countAs := func(tenantID, actorID uuid.UUID) (threads, messages int) {
		t.Helper()
		err := asChat(t, env, tenantID, actorID, func(tx pgx.Tx) error {
			return tx.QueryRow(ctx, `select (select count(*) from chat.threads), (select count(*) from chat.messages)`).Scan(&threads, &messages)
		})
		if err != nil {
			t.Fatalf("count: %v", err)
		}
		return threads, messages
	}
	if th, msg := countAs(env.Fx.TenantA, env.Fx.UserQuispe); th != 1 || msg != 1 {
		t.Errorf("the owner sees %d threads, %d messages; want 1, 1", th, msg)
	}
	if th, msg := countAs(env.Fx.TenantA, env.Fx.UserRojas); th != 0 || msg != 0 {
		t.Errorf("another user of the same school sees %d threads, %d messages; want none", th, msg)
	}
	if th, msg := countAs(env.Fx.TenantB, env.Fx.UserFlores); th != 0 || msg != 0 {
		t.Errorf("another school sees %d threads, %d messages; want none", th, msg)
	}

	err = asChat(t, env, env.Fx.TenantA, env.Fx.UserQuispe, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `insert into chat.threads (tenant_id, user_id) values ($1, $2)`, env.Fx.TenantB, env.Fx.UserQuispe)
		return err
	})
	if pgCode(err) != insufficientPrivilege {
		t.Errorf("writing a thread into another school: err = %v, want an RLS violation", err)
	}
	err = asChat(t, env, env.Fx.TenantA, env.Fx.UserQuispe, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `insert into chat.threads (tenant_id, user_id) values ($1, $2)`, env.Fx.TenantA, env.Fx.UserRojas)
		return err
	})
	if pgCode(err) != insufficientPrivilege {
		t.Errorf("writing a thread for another user: err = %v, want an RLS violation", err)
	}
}

func TestMawtaAppHasNoChatAccess(t *testing.T) {
	env := dbtest.Setup(t)
	ctx := context.Background()
	for _, relation := range []string{"chat.threads", "chat.messages", "chat_api.school", "chat_api.sections"} {
		err := env.App.WithTenantTx(ctx, tenantA(env), func(tx pgx.Tx) error {
			_, err := tx.Exec(ctx, `select 1 from `+relation+` limit 1`)
			return err
		})
		if pgCode(err) != insufficientPrivilege {
			t.Errorf("reading %s as mawta_app: err = %v, want permission denied", relation, err)
		}
	}
}

// Every table with a student_id must declare itself in the personal-data
// registry (privacy.minor_data_tables reads table comments). A new table that
// forgets fails here instead of silently missing from retention and deletion.
func TestEveryStudentReferenceIsDeclared(t *testing.T) {
	env := dbtest.Setup(t)
	rows, err := env.Admin.Pool.Query(context.Background(),
		`select table_name, column_name from privacy.undeclared_student_references`)
	if err != nil {
		t.Fatalf("query: %v", err)
	}
	defer rows.Close()
	for rows.Next() {
		var table, column string
		if err := rows.Scan(&table, &column); err != nil {
			t.Fatalf("scan: %v", err)
		}
		t.Errorf("%s.%s references a student but the table is not declared as holding minors' data", table, column)
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("rows: %v", err)
	}
}
