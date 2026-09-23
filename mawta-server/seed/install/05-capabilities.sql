-- ---------------------------------------------------------------------------
-- Capacidades CNEB: las sub-habilidades que componen cada competencia.
--
-- Adquirir capacidades por separado no vuelve competente a un estudiante —
-- serlo es usarlas de forma combinada — pero cada criterio de evaluación debe
-- anclarse a una capacidad concreta (evaluation_criteria.capability_id es NOT
-- NULL), así que sin estas filas no hay criterios posibles.
--
-- El id se deriva de md5('cap:' || código): determinista entre recargas sin
-- escribir 31 UUID literales.
-- ---------------------------------------------------------------------------

insert into capabilities (id, tenant_id, competency_id, code, name, sort_order)
select md5('cap:' || v.code)::uuid,
       '84d84ee4-816d-4035-a1ad-55efeee4f11e',
       c.id, v.code, v.name, v.ord
  from (values
    -- Matemática C1 — Resuelve problemas de cantidad
    ('MAT-C1','MAT-C1-CAP1','Traduce cantidades a expresiones numéricas',1),
    ('MAT-C1','MAT-C1-CAP2','Comunica su comprensión sobre los números y las operaciones',2),
    ('MAT-C1','MAT-C1-CAP3','Usa estrategias y procedimientos de estimación y cálculo',3),
    ('MAT-C1','MAT-C1-CAP4','Argumenta afirmaciones sobre las relaciones numéricas y las operaciones',4),
    -- Matemática C2 — Regularidad, equivalencia y cambio
    ('MAT-C2','MAT-C2-CAP1','Traduce datos y condiciones a expresiones algebraicas y gráficas',1),
    ('MAT-C2','MAT-C2-CAP2','Comunica su comprensión sobre las relaciones algebraicas',2),
    ('MAT-C2','MAT-C2-CAP3','Usa estrategias y procedimientos para encontrar equivalencias y reglas generales',3),
    ('MAT-C2','MAT-C2-CAP4','Argumenta afirmaciones sobre relaciones de cambio y equivalencia',4),
    -- Matemática C3 — Forma, movimiento y localización
    ('MAT-C3','MAT-C3-CAP1','Modela objetos con formas geométricas y sus transformaciones',1),
    ('MAT-C3','MAT-C3-CAP2','Comunica su comprensión sobre las formas y relaciones geométricas',2),
    ('MAT-C3','MAT-C3-CAP3','Usa estrategias y procedimientos para orientarse en el espacio',3),
    ('MAT-C3','MAT-C3-CAP4','Argumenta afirmaciones sobre relaciones geométricas',4),
    -- Matemática C4 — Gestión de datos e incertidumbre
    ('MAT-C4','MAT-C4-CAP1','Representa datos con gráficos y medidas estadísticas o probabilísticas',1),
    ('MAT-C4','MAT-C4-CAP2','Comunica su comprensión de los conceptos estadísticos y probabilísticos',2),
    ('MAT-C4','MAT-C4-CAP3','Usa estrategias y procedimientos para recopilar y procesar datos',3),
    ('MAT-C4','MAT-C4-CAP4','Sustenta conclusiones o decisiones con base en la información obtenida',4),
    -- Ciencias Sociales C1 — Construye interpretaciones históricas
    ('CCSS-C1','CCSS-C1-CAP1','Interpreta críticamente fuentes diversas',1),
    ('CCSS-C1','CCSS-C1-CAP2','Comprende el tiempo histórico',2),
    ('CCSS-C1','CCSS-C1-CAP3','Elabora explicaciones sobre procesos históricos',3),
    -- Ciencias Sociales C2 — Espacio y ambiente
    ('CCSS-C2','CCSS-C2-CAP1','Comprende las relaciones entre los elementos naturales y sociales',1),
    ('CCSS-C2','CCSS-C2-CAP2','Maneja fuentes de información para comprender el espacio geográfico y el ambiente',2),
    ('CCSS-C2','CCSS-C2-CAP3','Genera acciones para conservar el ambiente local y global',3),
    -- Ciencias Sociales C3 — Recursos económicos
    ('CCSS-C3','CCSS-C3-CAP1','Comprende las relaciones entre los elementos del sistema económico y financiero',1),
    ('CCSS-C3','CCSS-C3-CAP2','Toma decisiones económicas y financieras',2),
    -- Transversal 1 — Entornos virtuales generados por las TIC
    ('TR-C1','TR-C1-CAP1','Personaliza entornos virtuales',1),
    ('TR-C1','TR-C1-CAP2','Gestiona información del entorno virtual',2),
    ('TR-C1','TR-C1-CAP3','Interactúa en entornos virtuales',3),
    ('TR-C1','TR-C1-CAP4','Crea objetos virtuales en diversos formatos',4),
    -- Transversal 2 — Gestiona su aprendizaje de manera autónoma
    ('TR-C2','TR-C2-CAP1','Define metas de aprendizaje',1),
    ('TR-C2','TR-C2-CAP2','Organiza acciones estratégicas para alcanzar sus metas de aprendizaje',2),
    ('TR-C2','TR-C2-CAP3','Monitorea y ajusta su desempeño durante el proceso de aprendizaje',3)
  ) as v(comp_code, code, name, ord)
  join competencies c
    on c.code = v.comp_code
   and c.tenant_id = '84d84ee4-816d-4035-a1ad-55efeee4f11e';
