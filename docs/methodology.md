# Metodología · Fase 3

## Pregunta de investigación

> How effectively can a multilingual, knowledge-enriched information retrieval system identify Italian equivalents and context-appropriate substitutes for Mexican cooking ingredients?

El prototipo cubre ingredientes que se usan en México y términos útiles para buscarlos en Italia. La demostración incluye un alimento con un equivalente nominal (jitomate), un candidato a sustituto en un contexto específico (poblano) y una advertencia de no equivalencia (masa harina y polenta).

## Construcción del catálogo

- El catálogo contiene 78 ingredientes de la cocina mexicana y 15 referencias italianas. El extractor usa la API de Wikibase para recuperar etiquetas, alias y revisiones de los conceptos seleccionados. Una copia local de los datos permite regenerar el catálogo sin cambios aunque Wikidata se actualice. [Acceso a Wikidata y licencia de los datos](https://www.wikidata.org/wiki/Wikidata:Data_access/en)
- Los nombres mexicanos visibles, alias seleccionados y notas son entradas editoriales del catálogo. Un nombre italiano se muestra como equivalencia cuando figura en las etiquetas o alias del concepto asociado. Para vocabulario especializado pueden aparecer un nombre científico o una descripción útil para buscar el producto.
- Cada relación tiene un ingrediente de origen, destino, uso, justificación, limitaciones y fuentes. La revisión documental de las 29 sustituciones distingue el respaldo directo del uso de una inferencia a partir de características o funciones compartidas. Por ejemplo, la Universidad de Misuri propone yogur natural para un aderezo de crema agria, mientras que el morrón verde para rellenar se infiere de las características de ambos chiles. [University of Missouri Extension](https://extension.missouri.edu/publications/mp564) · [Secretaría de Agricultura](https://www.gob.mx/agricultura/es/articulos/mexico-cuna-del-chile-riqueza-genetica-que-da-sabor-al-mundo)
- La advertencia sobre tortillas se apoya en la diferencia de procesamiento entre la masa harina y la harina común de maíz. [Masienda · Guía de la masa harina](https://masienda.com/es/blogs/learn/guide-to-masa-harina) · [Wikidata · Polenta (Q131607)](https://www.wikidata.org/wiki/Q131607)
- Se usó Codex para implementar el prototipo, seleccionar fuentes, redactar relaciones y etiquetar el conjunto de desarrollo. La búsqueda y la evaluación consultan archivos locales.

## Recuperación de información

La búsqueda normaliza mayúsculas, tildes, puntuación y espacios. La coincidencia exacta tiene prioridad y favorece el nombre principal frente a un alias. Para consultas de dos o más palabras significativas, BM25 ordena los candidatos que contienen todas esas palabras en sus nombres, alias o nombres de referencia. La cobertura completa evita devolver, por ejemplo, leche condensada común al buscar una versión «sin azúcar». Cada palabra se indexa una vez por ficha. [Implementación de BM25 usada en el proyecto](https://github.com/dorianbrown/rank_bm25)

Cuando esas etapas no producen coincidencias, el buscador intenta completar prefijos y luego corregir uno o dos cambios según la longitud de la consulta, usando la distancia de Damerau-Levenshtein. La interfaz indica cuándo encontró palabras, completó un prefijo o corrigió una posible errata.

Las consultas con «para» o «per» pueden indicar un uso culinario, por ejemplo «chile poblano para rajas» o «amido di mais per addensare». El método completo recupera el ingrediente y busca relaciones con ese uso mediante un vocabulario bilingüe definido en `data/annotations.json`. Cuando el uso completo no se reconoce, la app muestra la ficha del ingrediente y omite las sugerencias. Las advertencias se etiquetan de forma distinta a las sustituciones.

## Evaluación

`data/evaluation.csv` registra 40 consultas de elaboración propia. Hay 37 consultas con ingrediente esperado, incluidas 14 de uso culinario, y tres que deberían quedar sin resultado. El caso «queso oaxaca» pasó de estar fuera del catálogo a tener ficha; los porcentajes de esta versión usan el nuevo denominador. Cada consulta contextual tiene conjuntos esperados de sustitutos y advertencias, que pueden estar vacíos.

Comparamos tres variantes sobre las mismas consultas. La primera aplica coincidencia exacta, la segunda agrega prefijos y distancia de edición, y la tercera agrega BM25 y el reconocimiento de usos. Como la tercera variante añade dos funciones juntas, la comparación mide el cambio del sistema completo. Una ablación posterior puede medir por separado el aporte de cada función.

- **Top-1 Accuracy** · proporción de consultas con una primera respuesta correcta.
- **Recall@3** · proporción media de ingredientes relevantes recuperados entre los tres primeros resultados de las consultas con respuestas esperadas.
- **Acierto contextual** · proporción de consultas de uso culinario con un primer ingrediente correcto y coincidencia completa de los conjuntos esperados de sustitutos y advertencias.
- **Abstención correcta** · proporción de los casos fuera del catálogo que devuelven cero resultados.
- **Cobertura de fuentes** · proporción de fichas mexicanas con al menos una URL registrada en el catálogo.
- **Aceptación culinaria** · proporción de sustituciones aceptadas entre las que tienen una revisión humana registrada. Se muestra como pendiente cuando hay cero revisiones.

### Resultados del conjunto de desarrollo

| Método | Top-1 Accuracy | Recall@3 | Abstención correcta | Acierto contextual |
| --- | ---: | ---: | ---: | ---: |
| Exacta | 29,7 % | 29,7 % | 100 % | 0 % |
| Exacta + difusa | 51,4 % | 51,4 % | 100 % | 0 % |
| BM25 + contexto | 97,3 % | 97,3 % | 100 % | 85,7 % |

El método completo falla en «¿Qué uso en vez de poblano en rajas?», una pregunta libre sin el patrón admitido. En «fécula de maíz para espesar una salsa sin gluten» sí recupera la fécula, pero se abstiene de sugerir un sustituto porque el uso incluye una restricción adicional que el vocabulario aún no interpreta. Las consultas y las etiquetas se diseñaron junto con el prototipo. Estas cifras describen el conjunto de desarrollo, y las tres abstenciones aportan evidencia limitada sobre consultas nuevas fuera del catálogo.

### Revisión culinaria

Para cada sustitución, una persona debe revisar si el destino cumple la función en el uso indicado y si las diferencias de sabor, textura o técnica son aceptables. Registra el resultado con `human_review` igual a `accepted` o `rejected` en la relación correspondiente de `data/annotations.json`, y reconstruye el catálogo. Las relaciones rechazadas se ocultan en la búsqueda y las fichas. La revisión documental de esta fase conserva las 29 propuestas pendientes de aceptación humana.

## Evaluación final

El conjunto final contiene 36 consultas nuevas y se guardó con sus respuestas esperadas antes de calcular las métricas. Incluye 14 consultas de identidad, cinco de sustitución por uso, ocho que requieren un ajuste, cinco casos sin sustituto apropiado y cuatro ingredientes fuera del catálogo. Once consultas se etiquetaron como habituales y 25 como especializadas. Las consultas y sus etiquetas se elaboraron con conocimiento del catálogo. Se incluyeron variantes en español e italiano, erratas y preguntas formuladas libremente.

Se comparan tres configuraciones sobre las mismas consultas.

1. **Traducción literal.** Busca coincidencias completas normalizadas entre los nombres principales en español e italiano del catálogo base. Requiere un par bilingüe documentado.
2. **BM25 + contexto con el catálogo base.** Usa las etiquetas, alias, usos y relaciones de la revisión `1621edf40e21f78b24b29ba091de2fcc81d479ac`, que contiene 67 fichas.
3. **BM25 + contexto con el catálogo ampliado.** Aplica el mismo buscador a las 93 fichas de la fase 2.

El archivo `data/evaluation_snapshot.json` guarda las dos versiones de los campos usados en la comparación, la revisión base y las huellas SHA-256 del catálogo ampliado y del CSV de consultas. Las huellas se calculan sobre texto UTF-8 con finales de línea LF. No se modificaron las consultas ni el buscador a partir de estos resultados.

| Sistema | Top-1 | Recall@3 | Uso culinario | Abstención contextual | Ajustes requeridos mostrados |
| --- | ---: | ---: | ---: | ---: | ---: |
| Traducción literal | 3/32 (9,4 %) | 9,4 % | 0/18 | 0/5 | 0/8 |
| BM25 + contexto, base | 17/32 (53,1 %) | 53,1 % | 7/18 (38,9 %) | 4/5 | 0/8 |
| BM25 + contexto, ampliado | 30/32 (93,8 %) | 93,8 % | 15/18 (83,3 %) | 5/5 | 5/8 |

Con el mismo buscador, Top-1 en consultas habituales fue 10/10 en ambas versiones. En consultas especializadas pasó de 7/22 a 20/22. Los tres sistemas se abstuvieron en las cuatro consultas de ingredientes fuera del catálogo.

El acierto de uso exige recuperar primero el ingrediente esperado, mostrar los conjuntos de sustitutos y advertencias esperados e incluir los ajustes requeridos. La abstención contextual exige recuperar el ingrediente y dejar vacía la lista de sustitutos. Un ajuste omitido se cuenta cuando aparece su sustituto sin el campo de ajuste. La cobertura de ajustes también considera las alternativas que faltan por completo.

| Sistema | Sustitutos incorrectos | Sustitutos omitidos | Advertencias omitidas | Ajustes omitidos en sustitutos mostrados |
| --- | ---: | ---: | ---: | ---: |
| Traducción literal | 0 | 16 | 3 | 0 |
| BM25 + contexto, base | 0 | 12 | 1 | 0 |
| BM25 + contexto, ampliado | 0 | 4 | 0 | 0 |

El catálogo ampliado recuperó la tostada de maíz, pero el buscador no reconoció «base crujiente» como uso. Tampoco recuperó el ingrediente de origen en dos preguntas abiertas, una sobre Oaxaca para quesadillas y otra sobre guajillo en adobo. Los tres casos dejaron cuatro opciones esperadas sin mostrar.

Estos resultados miden coincidencia con etiquetas editoriales en una muestra pequeña. La tasa de aceptación culinaria sigue pendiente de revisión humana. Para reproducir la evaluación, usa `python evaluation.py --final`. Añade `--group habitual` o `--group especializado` para consultar cada grupo.
