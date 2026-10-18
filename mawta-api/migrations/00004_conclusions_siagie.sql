-- Conclusiones descriptivas listas para SIAGIE.
--
-- SIAGIE acepta una conclusión descriptiva de 10 a 350 caracteres. Toda conclusión
-- de Mawta lo respeta, sea borrador o final: el agente escribe para SIAGIE y el
-- docente nunca guarda un texto que no se podría exportar. El servidor guarda el
-- body normalizado (un solo párrafo, sin saltos de línea) y lo valida; este check
-- es la última barrera.
--
-- Las conclusiones guardadas antes de esta regla se escribieron sin límite. Se
-- retiran todas con borrado lógico (deleted_at): siguen en la tabla para
-- auditoría, pero ya no cuentan para ningún requisito ni para la exportación.
--
-- También registra si la conclusión partió de una propuesta de Mawta que leyó
-- notas de voz.

-- +goose Up

alter table descriptive_conclusions
  add column generated_from_voice_notes boolean not null default false;

comment on column descriptive_conclusions.generated_from_voice_notes is
  'Verdadero cuando la conclusión partió de una propuesta de Mawta (conclusions) que usó al menos una nota de voz. Lo fija el servidor al guardar, a partir de agent_generations.result.used_voice_note_ids; el cliente no lo envía. Es un registro interno, no se muestra al docente.';

-- Retiro de las conclusiones previas a la regla de SIAGIE.
update descriptive_conclusions
   set deleted_at = now()
 where deleted_at is null;

alter table descriptive_conclusions
  add constraint dc_body_siagie check (
    deleted_at is not null
    or (char_length(body) between 10 and 350 and body !~ '[\r\n]'));

comment on constraint dc_body_siagie on descriptive_conclusions is
  'SIAGIE acepta de 10 a 350 caracteres en una sola línea. Aplica a borradores y finales; las filas retiradas (deleted_at) quedan fuera.';

-- +goose Down

-- Las conclusiones retiradas en el Up no se restauran: no se distinguen de las
-- borradas por otras razones.
alter table descriptive_conclusions drop constraint if exists dc_body_siagie;
alter table descriptive_conclusions drop column if exists generated_from_voice_notes;
