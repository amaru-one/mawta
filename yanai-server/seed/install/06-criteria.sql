-- ---------------------------------------------------------------------------
-- Criterios de evaluación.
--
-- Solo llevan criterios las competencias que se trabajan este año (MAT-C1..C4,
-- CCSS-C1..C2 y las dos transversales). CCSS-C3 queda DELIBERADAMENTE sin
-- criterios: la pantalla de criterios debe mostrarla como un vacío explícito,
-- y una competencia sin criterios tiene que poder distinguirse de una que sí
-- los tiene pero aún no se evaluó.
--
-- evaluation_criteria.capability_id es NOT NULL y compuesto sobre la misma
-- competencia: un criterio no puede flotar fuera de la estructura de su
-- competencia.
-- ---------------------------------------------------------------------------

insert into evaluation_criteria
  (id, tenant_id, competency_id, capability_id, code, description, sort_order)
select md5('crit:' || v.code)::uuid,
       '84d84ee4-816d-4035-a1ad-55efeee4f11e',
       cap.competency_id, cap.id, v.code, v.description, v.ord
  from (values
    ('MAT-C1-CAP1','MAT-C1-CR1','Expresa cantidades y magnitudes usando números enteros y racionales',1),
    ('MAT-C1-CAP3','MAT-C1-CR2','Selecciona y emplea estrategias de cálculo para resolver problemas con enteros',2),
    ('MAT-C1-CAP4','MAT-C1-CR3','Justifica el procedimiento elegido y la razonabilidad del resultado',3),
    ('MAT-C2-CAP1','MAT-C2-CR1','Plantea la ecuación o inecuación lineal que modela la situación',1),
    ('MAT-C2-CAP3','MAT-C2-CR2','Aplica propiedades de igualdad para hallar el valor desconocido',2),
    ('MAT-C2-CAP4','MAT-C2-CR3','Argumenta por qué dos expresiones algebraicas son equivalentes',3),
    ('MAT-C3-CAP1','MAT-C3-CR1','Representa formas bidimensionales y sus transformaciones en el plano',1),
    ('MAT-C3-CAP3','MAT-C3-CR2','Emplea estrategias para calcular perímetros, áreas y ubicaciones',2),
    ('MAT-C4-CAP1','MAT-C4-CR1','Organiza datos en tablas y gráficos estadísticos pertinentes',1),
    ('MAT-C4-CAP4','MAT-C4-CR2','Sustenta conclusiones sobre los datos a partir de medidas de tendencia central',2),
    ('CCSS-C1-CAP1','CCSS-C1-CR1','Distingue entre fuente primaria y secundaria, y evalúa su fiabilidad',1),
    ('CCSS-C1-CAP2','CCSS-C1-CR2','Ubica procesos históricos en secuencias temporales y establece simultaneidad',2),
    ('CCSS-C1-CAP3','CCSS-C1-CR3','Explica un proceso histórico relacionando causas y consecuencias',3),
    ('CCSS-C2-CAP1','CCSS-C2-CR1','Explica cómo interactúan los elementos naturales y sociales de un territorio',1),
    ('CCSS-C2-CAP2','CCSS-C2-CR2','Interpreta mapas, croquis e imágenes para describir el espacio geográfico',2),
    ('CCSS-C2-CAP3','CCSS-C2-CR3','Propone acciones concretas de conservación del ambiente en su localidad',3),
    ('TR-C1-CAP2','TR-C1-CR1','Selecciona y organiza información digital verificando su procedencia',1),
    ('TR-C2-CAP1','TR-C2-CR1','Define metas de aprendizaje alcanzables y verificables',1),
    ('TR-C2-CAP3','TR-C2-CR2','Ajusta sus estrategias cuando comprueba que no avanza hacia la meta',2)
  ) as v(cap_code, code, description, ord)
  join capabilities cap
    on cap.code = v.cap_code
   and cap.tenant_id = '84d84ee4-816d-4035-a1ad-55efeee4f11e';
