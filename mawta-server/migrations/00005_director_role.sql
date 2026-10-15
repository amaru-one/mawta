-- Rol director: el director del colegio inicia sesión en Mawta y entra a su
-- propia experiencia (el chat de dirección), nunca a la del docente. No tiene
-- fila en teachers. 'supervisor' queda reservado para otro caso de uso.

-- +goose Up

alter table memberships drop constraint memberships_role_check;
alter table memberships add constraint memberships_role_check
  check (role in ('teacher', 'student', 'supervisor', 'admin', 'director'));

alter table user_sessions drop constraint user_sessions_role_check;
alter table user_sessions add constraint user_sessions_role_check
  check (role in ('teacher', 'student', 'supervisor', 'admin', 'director'));

-- +goose Down

-- Falla si ya existen memberships o sesiones con role = 'director'.
alter table user_sessions drop constraint user_sessions_role_check;
alter table user_sessions add constraint user_sessions_role_check
  check (role in ('teacher', 'student', 'supervisor', 'admin'));

alter table memberships drop constraint memberships_role_check;
alter table memberships add constraint memberships_role_check
  check (role in ('teacher', 'student', 'supervisor', 'admin'));
