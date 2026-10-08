package repo

import (
	"context"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type MeResponse struct {
	Role string `json:"role"`
	User struct {
		DisplayName string `json:"display_name"`
		Email       string `json:"email"`
	} `json:"user"`
	Teacher struct {
		ID    uuid.UUID `json:"id"`
		Title *string   `json:"title"`
	} `json:"teacher"`
	Tenant struct {
		ID       uuid.UUID `json:"id"`
		Name     string    `json:"name"`
		City     *string   `json:"city"`
		Timezone string    `json:"timezone"`
	} `json:"tenant"`
}

func GetMe(ctx context.Context, tx pgx.Tx, teacherID uuid.UUID) (MeResponse, error) {
	var resp MeResponse
	err := tx.QueryRow(ctx, `
		select coalesce(u.display_name, u.given_name || ' ' || u.family_name), u.email,
		       t.id, t.title,
		       tn.id, tn.name, tn.city, tn.timezone
		  from teachers t
		  join memberships m on m.id = t.membership_id
		  join users u on u.id = m.user_id
		  join tenants tn on tn.id = t.tenant_id
		 where t.id = $1
	`, teacherID).Scan(
		&resp.User.DisplayName, &resp.User.Email,
		&resp.Teacher.ID, &resp.Teacher.Title,
		&resp.Tenant.ID, &resp.Tenant.Name, &resp.Tenant.City, &resp.Tenant.Timezone,
	)
	return resp, err
}
