# CNEB transcription report

## Scope and status

This is an incremental transcription, not the complete requested catalog. Mathematics is complete: four competencies, 16 capacities, 32 standards, and 324 grade performances. Every included source page was rendered with pypdfium2 and read visually. Primary-program text and local macOS Vision OCR were used as drafts and corrected against the rendered pages. No Internet sources were used. Source spelling, punctuation, apparent errors, and differences between editions are retained.

Only `mawta-server/curriculum/cneb/` is changed. Work is on `data/cneb-catalog`, created from `main` at `4af29aa`. No Go code, seed changes, push, or merge.

## Source conventions

Page references below are **PDF page numbers, starting at 1**. For the supplied CNEB and primary program, subtract 2 to obtain the printed page number. Secondary PDF and printed page numbers coincide. `nivel: 8` represents the CNEB's `DESTACADO`, as verified in the cycle table (CNEB PDF pp. 27–28). Grade/cycle assignments were verified on CNEB PDF pp. 90 and 92.

One performance is one top-level program bullet. Nested strategy lists remain in that performance, with `•` separators. Examples and cross-page continuations remain in the same performance. Footnote reference numbers are retained as superscripts; footnote bodies outside the bullet/standard are not inserted into the text. Figures accompanying examples are not representable by this text-only schema; the complete prose of those examples is retained (secondary pp. 159, 161, 162). Only line breaks, layout spacing, and end-of-line word splits have been joined.

## Mathematics inventory and sources

The CNEB order differs from the program order: `MAT-C3` is CNEB 26; `MAT-C4` is CNEB 25. The required existing codes are preserved. Program area/order references: primary PDF p. 232 and secondary p. 147.

| File | Competency | Capacities | Standards | CNEB capacity page | CNEB standard page |
| --- | --- | ---: | ---: | ---: | ---: |
| `c23.json` | Resuelve problemas de cantidad | 4 | 8 | 76 | 77 |
| `c24.json` | Resuelve problemas de regularidad, equivalencia y cambio | 4 | 8 | 78 | 79 |
| `c26.json` | Resuelve problemas de forma, movimiento y localización | 4 | 8 | 82 | 83 |
| `c25.json` | Resuelve problemas de gestión de datos e incertidumbre | 4 | 8 | 80 | 81 |

| Competency | Grade | Performance count | Program | PDF source pages |
| --- | --- | ---: | --- | --- |
| 23 | 1P | 7 | Primary | 239 |
| 23 | 2P | 7 | Primary | 239 |
| 23 | 3P | 7 | Primary | 240, 241 |
| 23 | 4P | 7 | Primary | 240, 241 |
| 23 | 5P | 7 | Primary | 242, 243 |
| 23 | 6P | 7 | Primary | 242, 243 |
| 23 | 1S | 9 | Secondary | 151, 152 |
| 23 | 2S | 10 | Secondary | 151, 152 |
| 23 | 3S | 10 | Secondary | 153, 154 |
| 23 | 4S | 9 | Secondary | 153, 154 |
| 23 | 5S | 9 | Secondary | 155 |
| 24 | 1P | 5 | Primary | 249 |
| 24 | 2P | 6 | Primary | 249 |
| 24 | 3P | 6 | Primary | 251 |
| 24 | 4P | 7 | Primary | 251 |
| 24 | 5P | 5 | Primary | 253 |
| 24 | 6P | 5 | Primary | 253 |
| 24 | 1S | 10 | Secondary | 158, 159 |
| 24 | 2S | 9 | Secondary | 158, 159 |
| 24 | 3S | 9 | Secondary | 160, 161 |
| 24 | 4S | 9 | Secondary | 160, 161 |
| 24 | 5S | 9 | Secondary | 162 |
| 26 | 1P | 7 | Primary | 258, 259 |
| 26 | 2P | 7 | Primary | 258, 259 |
| 26 | 3P | 8 | Primary | 260, 261 |
| 26 | 4P | 7 | Primary | 260, 261 |
| 26 | 5P | 8 | Primary | 262, 263 |
| 26 | 6P | 8 | Primary | 262, 263 |
| 26 | 1S | 8 | Secondary | 165, 166 |
| 26 | 2S | 8 | Secondary | 165, 166 |
| 26 | 3S | 8 | Secondary | 167, 168 |
| 26 | 4S | 8 | Secondary | 167, 168 |
| 26 | 5S | 8 | Secondary | 169 |
| 25 | 1P | 5 | Primary | 268 |
| 25 | 2P | 5 | Primary | 268 |
| 25 | 3P | 6 | Primary | 270 |
| 25 | 4P | 6 | Primary | 270 |
| 25 | 5P | 6 | Primary | 272 |
| 25 | 6P | 7 | Primary | 272 |
| 25 | 1S | 7 | Secondary | 172, 173 |
| 25 | 2S | 7 | Secondary | 172, 173 |
| 25 | 3S | 7 | Secondary | 174, 175 |
| 25 | 4S | 7 | Secondary | 174, 175 |
| 25 | 5S | 7 | Secondary | 176 |

## Differences between CNEB standards and program cycle descriptions

The JSON always keeps the supplied CNEB wording. References below are to the program's actual cycle-description paragraphs, not a later edition or a remembered standard.

- **23, cycle III:** primary p. 238 matches CNEB p. 77, except footnote reference 42 versus 40.
- **23, cycle IV:** primary p. 240 matches, except footnote 44 versus 39.
- **23, cycle V:** primary p. 242 matches, except footnote 45 versus 38.
- **23, cycle VI:** secondary p. 151 adds `aumentos`: program `racionales, aumentos y descuentos porcentuales sucesivos`; CNEB p. 77 `racionales, y descuentos porcentuales sucesivos`.
- **23, cycle VII:** secondary p. 153 says `con números racionales o irracionales`; CNEB p. 77 and the cycle VII paragraph on secondary p. 155 say `con números irracionales o racionales`. Otherwise the paragraphs match.
- **24, cycles III–V:** primary pp. 248, 250, 252 match CNEB p. 79.
- **24, cycle VI:** secondary p. 158 matches CNEB p. 79 except footnote 43 versus 41.
- **24, cycle VII:** secondary pp. 160, 162 match CNEB p. 79.
- **25, cycles III and V:** primary pp. 268, 271 match CNEB p. 81.
- **25, cycle IV:** primary p. 269 differs from CNEB p. 81 in three places: `tema de estudio, recolecta` versus `tema de estudio de recolecta`; `a partir de esta información, elabora` versus `a partir de esta información y elabora`; and `menos probable, y justifica` versus `menos probable, justifica`.
- **25, cycles VI–VII:** secondary pp. 172, 174, 176 match CNEB p. 81.
- **26, cycle III:** primary p. 258 adds `usando algunos términos del lenguaje geométrico` after `puntos de referencia`; CNEB p. 83 ends the sentence at `puntos de referencia.`
- **26, cycles IV and V:** primary pp. 260, 262 differ extensively from the corresponding CNEB p. 83 paragraphs. The complete program paragraphs are reproduced below to make the discrepancy reviewable. In particular, the CNEB level 4 describes corners, curved/straight sides, and nonstandard length measurement; the program cycle IV describes polygons, symmetry, translations, surface and capacity. The CNEB level 5 describes right angles, parallel/perpendicular lines, translations, and compound figures; the program cycle V describes prisms, rotations, scaling, and conversions.
- **26, cycle VI:** secondary p. 165 says `Clasifica prismas, pirámides y polígonos, según sus propiedades.`; CNEB p. 83 says `Clasifica prismas, pirámides, polígonos y círculos, según sus propiedades.` The program also says `formas, relaciones entre áreas`; the CNEB says `formas, entre relaciones entre áreas`.
- **26, cycle VII:** secondary pp. 167, 169 match CNEB p. 83.

### Complete differing primary geometry paragraphs

Primary PDF p. 260, cycle IV:

> Resuelve problemas en los que modela características y datos de ubicación de los objetos a formas bidimensionales y tridimensionales, sus elementos, propiedades, su movimiento y ubicación en el plano cartesiano. Describe con lenguaje geométrico, estas formas reconociendo ángulos rectos, número de lados y vértices del polígono, así como líneas paralelas y perpendiculares, identifica formas simétricas y realiza traslaciones, en cuadrículas. Así también elabora croquis, donde traza y describe desplazamientos y posiciones, usando puntos de referencia. Emplea estrategias y procedimientos para trasladar y construir formas a través de la composición y descomposición, y para medir la longitud, superficie y capacidad de los objetos, usando unidades convencionales y no convencionales, recursos e instrumentos de medición. Elabora afirmaciones sobre las figuras compuestas; así como relaciones entre una forma tridimensional y su desarrollo en el plano; las explica con ejemplos concretos y gráficos.

Primary PDF p. 262, cycle V:

> Resuelve problemas en los que modela las características y la ubicación de objetos del entorno a formas bidimensionales y tridimensionales, sus propiedades, su ampliación, reducción o rotación. Describe y clasifica prismas rectos, cuadriláteros, triángulos, círculos, por sus elementos: vértices, lados, caras, ángulos, y por sus propiedades; usando lenguaje geométrico. Realiza giros en cuartos y medias vueltas, traslaciones, ampliación y reducción de formas bidimensionales, en el plano cartesiano. Describe recorridos y ubicaciones en planos. Emplea procedimientos e instrumentos para ampliar, reducir, girar y construir formas; así como para estimar o medir la longitud, superficie y capacidad de los objetos, seleccionando la unidad de medida convencional apropiada y realizando conversiones. Explica sus afirmaciones sobre relaciones entre elementos de las formas geométricas y sus atributos medibles, con ejemplos concretos y propiedades.

### Source anomalies retained

CNEB p. 79, levels 1 and 2 of competency 24, refer back to `Resuelve problemas de regularidad, equivalencia y cambio` itself. This was not replaced with a different competency. CNEB p. 83, level 5, prints `medición.Elabora` without a space, which is retained. The primary program's cycle descriptions were not used to silently repair either source.

## Comparison with `ejemplo-san-felipe.json`

All 16 Mathematics capacity names were compared, in order. Twelve match exactly. Four differ:

| Existing seed code | Seed name | Supplied CNEB name | PDF page |
| --- | --- | --- | ---: |
| MAT-C2-CAP1 | Traduce datos y condiciones a expresiones algebraicas y gráficas | Traduce datos y condiciones a expresiones algebraicas | 78 |
| MAT-C2-CAP3 | Usa estrategias y procedimientos para encontrar equivalencias y reglas generales | Usa estrategias y procedimientos para encontrar reglas generales | 78 |
| MAT-C4-CAP2 | Comunica su comprensión de los conceptos estadísticos y probabilísticos | Comunica la comprensión de los conceptos estadísticos y probabilísticos | 80 |
| MAT-C4-CAP4 | Sustenta conclusiones o decisiones con base en la información obtenida | Sustenta conclusiones o decisiones con base en información obtenida | 80 |

The seed file is unchanged. CCSS and transversal comparisons remain pending until their source transcription is complete.

## Legibility and source limitations

No unresolved word readings remain in the included Mathematics texts. Secondary pp. 151, 153, 155, 158, 160, 162, 165, 167, 172 contain seals near text; affected prose was checked visually, and mathematical signs on p. 160 were additionally inspected at 4× rendering scale. This statement applies only to the included Mathematics pages, not the unprocessed remainder.

The supplied CNEB is **not a source containing 31 numbered competency descriptions**: its index (PDF pp. 4–5) enumerates 1–29, including TIC 28 and autonomous learning 29. Religious Education appears in the area table (PDF p. 92), but the index does not assign it competencies 30 and 31. No such numbering is invented in these JSON files. A clarification was requested about numbering the two program Religious Education competencies as catalog 30/31; their CNEB-number/source requirement remains unresolved until answered and verified.

## Areas compared with the requested codes

No missing or additional in-scope areas were found in the program tables of contents (primary PDF p. 9; secondary p. 3). Primary lists PS, EF, AYC, COM, CAS, ING, MAT, CYT, ER. Secondary lists DPCC, CCSS, EF, AYC, COM, CAS, ING, MAT, CYT, EPT, ER. Tutoría is excluded as instructed. Only completed areas are currently added to `areas.json`, so untranscribed competencies are not referenced.

## Validation and remaining work

Validation ran from `/private/tmp/cneb-transcripcion/validate.py`, outside the repository. It checks JSON validity and duplicate keys; exact allowed key sets; unique codes and competency numbers; area/file references; consecutive capacities; exactly levels 1–8; valid grades and consecutive performance orders; all eleven Mathematics grades; whitespace, control characters, soft hyphens, and residual word-break hyphens. The completed Mathematics area passes: 4 competencies, 32 standards, 324 performances.

The full-catalog presence check is explicitly **incomplete**, not passing: competencies 1–22 and 27–31 are absent. Next: CCSS competencies 17–19, including all primary Personal Social performances, then the other areas and the two transversals. Their source pages, counts, legibility checks, and standard/seed comparisons remain to be completed. Resolve the Religious Education numbering/source discrepancy before claiming all 31 CNEB-numbered files.
