package repo

import (
	"context"
	"net/netip"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// ── pre-tenant, via db.WithAuthTx ───────────────────────────────────────

// LoginCandidate is one users row matched by username, on the pre-tenant
// login_lookup policy path.
type LoginCandidate struct {
	UserID       uuid.UUID
	PasswordHash string
	Status       string
	LockedUntil  *time.Time
}

// FindLoginCandidate reads the user matching lower(username). pgx.ErrNoRows
// when there is no match — the caller must still run auth.VerifyPassword
// against auth.DummyHash() so a missing username takes the same time as a
// wrong password.
func FindLoginCandidate(ctx context.Context, tx pgx.Tx, username string) (LoginCandidate, error) {
	var c LoginCandidate
	err := tx.QueryRow(ctx, `
		select id, password_hash, status, locked_until
		  from users
		 where lower(username) = lower($1) and password_hash is not null and deleted_at is null
	`, username).Scan(&c.UserID, &c.PasswordHash, &c.Status, &c.LockedUntil)
	return c, err
}

// ResolvedMembership is the user's single non-revoked membership.
// memberships_one_school_per_user guarantees there is at most one, so
// unlike an early draft of this design, there is no multiple-memberships
// case to handle here.
type ResolvedMembership struct {
	TenantID     uuid.UUID
	MembershipID uuid.UUID
	Role         string
}

// ResolveMembership returns the user's one active-or-invited membership.
// pgx.ErrNoRows means the account has none (no_membership).
func ResolveMembership(ctx context.Context, tx pgx.Tx, userID uuid.UUID) (ResolvedMembership, error) {
	var m ResolvedMembership
	err := tx.QueryRow(ctx, `
		select tenant_id, id, role
		  from memberships
		 where user_id = $1 and deleted_at is null and status <> 'revoked'
	`, userID).Scan(&m.TenantID, &m.MembershipID, &m.Role)
	return m, err
}

// RecordLoginFailure increments failed_login_count and, at maxFailures,
// locks the account for lockFor.
func RecordLoginFailure(ctx context.Context, tx pgx.Tx, userID uuid.UUID, maxFailures int, lockFor time.Duration) error {
	_, err := tx.Exec(ctx, `
		update users
		   set failed_login_count = failed_login_count + 1,
		       locked_until = case when failed_login_count + 1 >= $2
		                           then now() + make_interval(secs => $3)
		                           else locked_until
		                      end
		 where id = $1
	`, userID, maxFailures, lockFor.Seconds())
	return err
}

// RecordLoginSuccess resets the failure counter/lock and stamps last_login_at.
func RecordLoginSuccess(ctx context.Context, tx pgx.Tx, userID uuid.UUID) error {
	_, err := tx.Exec(ctx, `
		update users
		   set failed_login_count = 0, locked_until = null, last_login_at = now()
		 where id = $1
	`, userID)
	return err
}

// NewSession is the row CreateSession inserts.
type NewSession struct {
	TokenHash    []byte
	UserID       uuid.UUID
	TenantID     uuid.UUID
	MembershipID uuid.UUID
	Role         string
	ExpiresAt    time.Time
	UserAgent    string
	IP           *netip.Addr
}

func CreateSession(ctx context.Context, tx pgx.Tx, s NewSession) (uuid.UUID, error) {
	var id uuid.UUID
	err := tx.QueryRow(ctx, `
		insert into user_sessions (token_hash, user_id, tenant_id, membership_id, role, expires_at, user_agent, ip)
		values ($1, $2, $3, $4, $5, $6, nullif($7, ''), $8)
		returning id
	`, s.TokenHash, s.UserID, s.TenantID, s.MembershipID, s.Role, s.ExpiresAt, s.UserAgent, ipToText(s.IP)).Scan(&id)
	return id, err
}

func ipToText(ip *netip.Addr) *string {
	if ip == nil || !ip.IsValid() {
		return nil
	}
	s := ip.String()
	return &s
}

// SessionRow is a live (not revoked) session, joined against nothing else —
// tenant_id/membership_id/role are denormalised onto the row precisely so
// this single pre-tenant read is enough to build a db.TenantCtx.
type SessionRow struct {
	ID           uuid.UUID
	UserID       uuid.UUID
	TenantID     uuid.UUID
	MembershipID uuid.UUID
	Role         string
	LastSeenAt   time.Time
	ExpiresAt    time.Time
}

// FindLiveSession reads by exact token hash where revoked_at is null.
// pgx.ErrNoRows covers both "no such session" and "already revoked" — the
// caller cannot and need not distinguish them.
func FindLiveSession(ctx context.Context, tx pgx.Tx, tokenHash []byte) (SessionRow, error) {
	var s SessionRow
	err := tx.QueryRow(ctx, `
		select id, user_id, tenant_id, membership_id, role, last_seen_at, expires_at
		  from user_sessions
		 where token_hash = $1 and revoked_at is null
	`, tokenHash).Scan(&s.ID, &s.UserID, &s.TenantID, &s.MembershipID, &s.Role, &s.LastSeenAt, &s.ExpiresAt)
	return s, err
}

// TouchSession bumps last_seen_at, but only if it's been more than
// minInterval — called on every request, so a write per request would turn
// every GET into a read-write transaction.
func TouchSession(ctx context.Context, tx pgx.Tx, id uuid.UUID, minInterval time.Duration) error {
	_, err := tx.Exec(ctx, `
		update user_sessions
		   set last_seen_at = now()
		 where id = $1 and last_seen_at < now() - make_interval(secs => $2)
	`, id, minInterval.Seconds())
	return err
}

func RevokeSession(ctx context.Context, tx pgx.Tx, id uuid.UUID, reason string) error {
	_, err := tx.Exec(ctx, `
		update user_sessions set revoked_at = now(), revoked_reason = $2
		 where id = $1 and revoked_at is null
	`, id, reason)
	return err
}

func RevokeSessionByTokenHash(ctx context.Context, tx pgx.Tx, tokenHash []byte, reason string) error {
	_, err := tx.Exec(ctx, `
		update user_sessions set revoked_at = now(), revoked_reason = $2
		 where token_hash = $1 and revoked_at is null
	`, tokenHash, reason)
	return err
}

// RevokeUserSessions revokes every live session for a user — called on a
// password change.
func RevokeUserSessions(ctx context.Context, tx pgx.Tx, userID uuid.UUID, reason string) error {
	_, err := tx.Exec(ctx, `
		update user_sessions set revoked_at = now(), revoked_reason = $2
		 where user_id = $1 and revoked_at is null
	`, userID, reason)
	return err
}

// PruneSessions hard-deletes rows revoked or expired more than retain ago.
// Called opportunistically at the end of a successful login — there is no
// scheduler in this codebase (see internal/worker/SPEC.md) to run it as a
// job, and a session table is small enough that an on-login sweep is enough.
func PruneSessions(ctx context.Context, tx pgx.Tx, retain time.Duration) (int64, error) {
	tag, err := tx.Exec(ctx, `
		delete from user_sessions
		 where (revoked_at is not null and revoked_at < now() - make_interval(secs => $1))
		    or expires_at < now() - make_interval(secs => $1)
	`, retain.Seconds())
	if err != nil {
		return 0, err
	}
	return tag.RowsAffected(), nil
}

// ── post-tenant, via db.WithTenantTx ────────────────────────────────────

// ResolveTeacher is the surviving half of the old tenantAuth query: the
// membership must still be active and still carry a teachers row.
func ResolveTeacher(ctx context.Context, tx pgx.Tx, userID uuid.UUID) (uuid.UUID, error) {
	var teacherID uuid.UUID
	err := tx.QueryRow(ctx, `
		select t.id
		  from memberships m
		  join teachers t on t.membership_id = m.id and t.deleted_at is null
		 where m.user_id = $1
		   and m.tenant_id = app.current_tenant_id()
		   and m.status = 'active'
		   and m.deleted_at is null
	`, userID).Scan(&teacherID)
	return teacherID, err
}
