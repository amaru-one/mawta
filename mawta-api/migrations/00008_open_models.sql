-- Modelos abiertos (chat-director D004): los agentes y el chat del director
-- corren en el servidor de modelos del colegio o en OpenRouter.
--
-- 1. Sin costo por generación: con modelos propios no hay un precio por token
--    que registrar. Se guardan tokens y tiempos, no dinero.
-- 2. El historial del chat del director se vacía: los hilos de prueba se
--    guardaron en el formato de Anthropic y el chat pasa al formato compatible
--    con OpenAI. Los checkpoints viejos de LangGraph quedan huérfanos y nunca
--    se vuelven a leer.

-- +goose Up

alter table agent_generations drop column cost_usd;

-- chat.messages y chat.question_bank se borran en cascada.
delete from chat.threads;

-- +goose Down

alter table agent_generations
  add column cost_usd numeric(10, 6) not null default 0 check (cost_usd >= 0);

comment on column agent_generations.cost_usd is
  'Costo estimado de las llamadas al modelo de esta generación, según la tabla de precios del servidor. Sirve para seguir el gasto por agente y por colegio.';
