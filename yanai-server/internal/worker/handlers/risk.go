package handlers

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/repo"
)

type riskPayload struct {
	ClassID   uuid.UUID  `json:"class_id"`
	StudentID *uuid.UUID `json:"student_id"`
}

type riskRule struct {
	ID       uuid.UUID
	Code     string
	Version  string
	Params   map[string]float64
	Severity string
}

// RiskDetect evaluates the tenant's active rules (consecutive absences,
// level drop) for one student or a whole class roster, opening or
// refreshing risk_flags and — on a fresh flag — writing evidence and an
// alert notification.
func RiskDetect(ctx context.Context, tx pgx.Tx, payload []byte) error {
	var p riskPayload
	if err := json.Unmarshal(payload, &p); err != nil {
		return err
	}

	rules, err := loadActiveRules(ctx, tx)
	if err != nil {
		return err
	}
	if len(rules) == 0 {
		return nil
	}

	var targets []uuid.UUID
	if p.StudentID != nil {
		targets = []uuid.UUID{*p.StudentID}
	} else {
		today, err := tenantToday(ctx, tx)
		if err != nil {
			return err
		}
		targets, err = repo.RosterAsOf(ctx, tx, p.ClassID, today)
		if err != nil {
			return err
		}
	}

	recipientTeacherID, err := currentTitularTeacher(ctx, tx, p.ClassID)
	if err != nil {
		if err == pgx.ErrNoRows {
			return nil // no titular assigned; nothing to notify
		}
		return err
	}

	for _, studentID := range targets {
		for _, rule := range rules {
			switch rule.Code {
			case "consecutive_absences":
				if err := checkConsecutiveAbsences(ctx, tx, studentID, p.ClassID, rule, recipientTeacherID); err != nil {
					return err
				}
			case "level_drop":
				if err := checkLevelDrop(ctx, tx, studentID, p.ClassID, rule, recipientTeacherID); err != nil {
					return err
				}
			}
		}
	}
	return nil
}

func loadActiveRules(ctx context.Context, tx pgx.Tx) ([]riskRule, error) {
	rows, err := tx.Query(ctx, `
		select id, code, version, params, severity from risk_rules
		 where is_active = true and deleted_at is null
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []riskRule
	for rows.Next() {
		var r riskRule
		var paramsRaw []byte
		if err := rows.Scan(&r.ID, &r.Code, &r.Version, &paramsRaw, &r.Severity); err != nil {
			return nil, err
		}
		_ = json.Unmarshal(paramsRaw, &r.Params)
		out = append(out, r)
	}
	return out, rows.Err()
}

func currentTitularTeacher(ctx context.Context, tx pgx.Tx, classID uuid.UUID) (uuid.UUID, error) {
	var id uuid.UUID
	err := tx.QueryRow(ctx, `
		select teacher_id from class_teachers
		 where class_id = $1 and role = 'titular' and deleted_at is null
		   and starts_on <= current_date and (ends_on is null or ends_on >= current_date)
		 limit 1
	`, classID).Scan(&id)
	return id, err
}

func studentName(ctx context.Context, tx pgx.Tx, studentID uuid.UUID) (string, error) {
	var name string
	err := tx.QueryRow(ctx, `
		select coalesce(preferred_name, given_name) || ' ' || paternal_surname
		  from students where id = $1
	`, studentID).Scan(&name)
	return name, err
}

func checkConsecutiveAbsences(ctx context.Context, tx pgx.Tx, studentID, classID uuid.UUID, rule riskRule, recipientTeacherID uuid.UUID) error {
	threshold := int(rule.Params["consecutive_absences"])
	if threshold <= 0 {
		threshold = 3
	}

	rows, err := tx.Query(ctx, `
		select id, status, session_date from attendance_records
		 where student_id = $1 and class_id = $2 and deleted_at is null
		 order by session_date desc limit 10
	`, studentID, classID)
	if err != nil {
		return err
	}
	var evidenceIDs []uuid.UUID
	for rows.Next() {
		var id uuid.UUID
		var status string
		var sessionDate any
		if err := rows.Scan(&id, &status, &sessionDate); err != nil {
			rows.Close()
			return err
		}
		if status != "absent" {
			break
		}
		evidenceIDs = append(evidenceIDs, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}

	if len(evidenceIDs) < threshold {
		return resolveFlagIfActive(ctx, tx, studentID, classID, rule.ID)
	}

	name, err := studentName(ctx, tx, studentID)
	if err != nil {
		return err
	}
	reasonText := fmt.Sprintf("%d ausencias seguidas", len(evidenceIDs))
	title := fmt.Sprintf("%s acumula %s", name, reasonText)

	flagID, inserted, err := upsertRiskFlag(ctx, tx, studentID, &classID, rule, "attendance", reasonText)
	if err != nil {
		return err
	}
	if !inserted {
		return nil
	}

	for _, evID := range evidenceIDs {
		if _, err := tx.Exec(ctx, `
			insert into risk_flag_evidence (tenant_id, risk_flag_id, entity_type, entity_id, occurred_at)
			select app.current_tenant_id(), $1, 'attendance_record', $2, ar.session_date
			  from attendance_records ar where ar.id = $2
		`, flagID, evID); err != nil {
			return err
		}
	}

	return notifyAlert(ctx, tx, recipientTeacherID, "consecutive_absences", rule.Severity, title, reasonText, studentID, classID, flagID)
}

func checkLevelDrop(ctx context.Context, tx pgx.Tx, studentID, classID uuid.UUID, rule riskRule, recipientTeacherID uuid.UUID) error {
	minDrop := int(rule.Params["min_drop"])
	if minDrop <= 0 {
		minDrop = 1
	}
	sessionsWindow := int(rule.Params["level_drop_sessions"])
	if sessionsWindow <= 0 {
		sessionsWindow = 3
	}

	var trend *string
	var curLevelID, prevLevelID *uuid.UUID
	err := tx.QueryRow(ctx, `
		select trend, scale_level_id, previous_scale_level_id from computed_grades
		 where student_id = $1 and class_id = $2 and superseded_at is null and deleted_at is null
	`, studentID, classID).Scan(&trend, &curLevelID, &prevLevelID)
	if err == pgx.ErrNoRows {
		return resolveFlagIfActive(ctx, tx, studentID, classID, rule.ID)
	}
	if err != nil {
		return err
	}
	if trend == nil || *trend != "down" || curLevelID == nil || prevLevelID == nil {
		return resolveFlagIfActive(ctx, tx, studentID, classID, rule.ID)
	}

	var curOrdinal, prevOrdinal int
	var curCode, prevCode string
	if err := tx.QueryRow(ctx, `select ordinal, code from grade_scale_levels where id = $1`, *curLevelID).Scan(&curOrdinal, &curCode); err != nil {
		return err
	}
	if err := tx.QueryRow(ctx, `select ordinal, code from grade_scale_levels where id = $1`, *prevLevelID).Scan(&prevOrdinal, &prevCode); err != nil {
		return err
	}

	if prevOrdinal-curOrdinal < minDrop {
		return resolveFlagIfActive(ctx, tx, studentID, classID, rule.ID)
	}

	name, err := studentName(ctx, tx, studentID)
	if err != nil {
		return err
	}
	reasonText := fmt.Sprintf("Bajó de %s a %s en las últimas %d clases", prevCode, curCode, sessionsWindow)
	title := fmt.Sprintf("%s %s", name, reasonText)

	flagID, inserted, err := upsertRiskFlag(ctx, tx, studentID, &classID, rule, "computed_grade", reasonText)
	if err != nil {
		return err
	}
	if !inserted {
		return nil
	}

	if _, err := tx.Exec(ctx, `
		insert into risk_flag_evidence (tenant_id, risk_flag_id, entity_type, entity_id, occurred_at)
		select app.current_tenant_id(), $1, 'computed_grade', cg.id, cg.computed_at
		  from computed_grades cg
		 where cg.student_id = $2 and cg.class_id = $3 and cg.superseded_at is null and cg.deleted_at is null
	`, flagID, studentID, classID); err != nil {
		return err
	}

	return notifyAlert(ctx, tx, recipientTeacherID, "level_drop", rule.Severity, title, reasonText, studentID, classID, flagID)
}

// upsertRiskFlag opens or refreshes the one active flag for
// (student, class, rule). The ON CONFLICT target reproduces the
// risk_flags_open_key partial unique index exactly, including its
// coalesce(class_id, zero-uuid) expression.
func upsertRiskFlag(ctx context.Context, tx pgx.Tx, studentID uuid.UUID, classID *uuid.UUID, rule riskRule, reasonCode, reasonText string) (uuid.UUID, bool, error) {
	var id uuid.UUID
	var inserted bool
	err := tx.QueryRow(ctx, `
		insert into risk_flags (tenant_id, student_id, class_id, rule_id, rule_version, severity, reason_code, reason_text)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7)
		on conflict (student_id, coalesce(class_id, '00000000-0000-0000-0000-000000000000'::uuid), rule_id)
		  where status = 'active' and deleted_at is null
		do update set last_evaluated_at = now(), reason_text = excluded.reason_text
		returning id, (xmax = 0)
	`, studentID, classID, rule.ID, rule.Version, rule.Severity, reasonCode, reasonText).Scan(&id, &inserted)
	return id, inserted, err
}

func resolveFlagIfActive(ctx context.Context, tx pgx.Tx, studentID, classID, ruleID uuid.UUID) error {
	_, err := tx.Exec(ctx, `
		update risk_flags set status = 'resolved', resolved_at = now()
		 where student_id = $1
		   and coalesce(class_id, '00000000-0000-0000-0000-000000000000'::uuid) = coalesce($2, '00000000-0000-0000-0000-000000000000'::uuid)
		   and rule_id = $3 and status = 'active' and deleted_at is null
	`, studentID, classID, ruleID)
	return err
}

func notifyAlert(ctx context.Context, tx pgx.Tx, recipientTeacherID uuid.UUID, category, severity, title, body string, studentID, classID, riskFlagID uuid.UUID) error {
	dedupeKey := category + ":" + studentID.String() + ":" + classID.String()
	_, err := tx.Exec(ctx, `
		insert into notifications (tenant_id, recipient_teacher_id, kind, category, severity, title, body,
		                            student_id, class_id, risk_flag_id, source, dedupe_key)
		values (app.current_tenant_id(), $1, 'alert', $2, $3, $4, $5, $6, $7, $8, 'rule', $9)
		on conflict (recipient_teacher_id, dedupe_key) where dedupe_key is not null and deleted_at is null
		do nothing
	`, recipientTeacherID, category, severity, title, body, studentID, classID, riskFlagID, dedupeKey)
	return err
}
