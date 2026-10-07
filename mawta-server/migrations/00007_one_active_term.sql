-- Un solo periodo activo por nivel. Hasta ahora nada impedía que varios
-- periodos de un mismo año estuvieran 'active' a la vez (el onboarding los
-- dejaba todos activos), y "el periodo activo" era una fila cualquiera: las
-- pantallas leían un periodo y la evidencia estaba en otro.
--
-- Significado de status desde aquí:
--   active   : el periodo en curso de su nivel. A lo sumo uno por (año, nivel).
--   planned  : aún no empieza. Acepta notas (solo closed/archived las rechazan).
--   closed   : cerrado; solo lectura. Se cierra a mano, antes de activar el
--              siguiente.
-- No tener ningún periodo activo es un estado válido (entre dos periodos): la
-- base no exige uno, solo prohíbe dos. El relevo es manual y estricto: primero
--   update terms set status = 'closed', closed_at = now() where id = '<activo>';
-- y después
--   update terms set status = 'active' where id = '<siguiente>';
-- Activar uno sin cerrar el anterior es rechazado por el índice.

-- +goose Up

-- Normaliza los datos existentes. Por (año, nivel) se conserva activo el
-- periodo que contiene hoy, si no el siguiente, si no el último (el mismo
-- orden que ResolvePlanTerm). Los que terminaron antes pasan a closed y los
-- posteriores a planned.
with active as (
  select id, academic_year_id, coalesce(stage, '') as stage_key, starts_on, ends_on
    from terms
   where status = 'active' and deleted_at is null
),
keep as (
  select distinct on (academic_year_id, stage_key) id, academic_year_id, stage_key, starts_on
    from active
   order by academic_year_id, stage_key,
            case when current_date between starts_on and ends_on then 0
                 when starts_on > current_date then 1
                 else 2 end,
            case when starts_on > current_date then starts_on end,
            ends_on desc
)
update terms t
   set status    = case when t.ends_on < k.starts_on then 'closed' else 'planned' end,
       closed_at = case when t.ends_on < k.starts_on then now() end
  from active a
  join keep k on k.academic_year_id = a.academic_year_id and k.stage_key = a.stage_key
 where t.id = a.id and t.id <> k.id;

create unique index terms_one_active_key
  on terms (academic_year_id, coalesce(stage, ''))
  where status = 'active' and deleted_at is null;

comment on index terms_one_active_key is
  'A lo sumo un periodo activo por año y nivel (stage), la misma clave que terms_no_overlap. Es por nivel y no por tenant porque un colegio puede llevar calendarios distintos por nivel. No exige que haya uno: entre dos periodos puede no haber ninguno activo.';

-- +goose Down
drop index if exists terms_one_active_key;
