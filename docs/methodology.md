# Metodología · Fase 3

## Pregunta de investigación

> How effectively can a multilingual, knowledge-enriched information retrieval system identify Italian equivalents and context-appropriate substitutes for Mexican cooking ingredients?

El prototipo cubre ingredientes que se usan en México y términos útiles para buscarlos en Italia. La demostración incluye un alimento con un equivalente nominal (jitomate), un candidato a sustituto en un contexto específico (poblano) y una advertencia de no equivalencia (masa harina y polenta).

## Construcción del catálogo

- El catálogo contiene 53 ingredientes de la cocina mexicana y seis referencias italianas. El extractor usa la API de Wikibase para recuperar etiquetas, alias y revisiones de los conceptos seleccionados. Una copia local de los datos permite regenerar el catálogo sin cambios aunque Wikidata se actualice. [Acceso a Wikidata y licencia de los datos](https://www.wikidata.org/wiki/Wikidata:Data_access/en)
- Los nombres mexicanos visibles, alias seleccionados y notas son entradas editoriales del catálogo. Un nombre italiano se muestra como equivalencia cuando figura en las etiquetas o alias del concepto asociado. Para vocabulario especializado pueden aparecer un nombre científico o una descripción útil para buscar el producto.
- Cada relación tiene un ingrediente de origen, destino, uso, justificación, limitaciones y fuentes. La revisión documental de las 15 sustituciones distingue el respaldo directo del uso de una inferencia a partir de características o funciones compartidas. Por ejemplo, la Universidad de Misuri propone yogur natural para un aderezo de crema agria, mientras que el morrón verde para rellenar se infiere de las características de ambos chiles. [University of Missouri Extension](https://extension.missouri.edu/publications/mp564) · [Secretaría de Agricultura](https://www.gob.mx/agricultura/es/articulos/mexico-cuna-del-chile-riqueza-genetica-que-da-sabor-al-mundo)
- La advertencia sobre tortillas se apoya en la diferencia de procesamiento entre la masa harina y la harina común de maíz. [Masienda · Guía de la masa harina](https://masienda.com/es/blogs/learn/guide-to-masa-harina) · [Wikidata · Polenta (Q131607)](https://www.wikidata.org/wiki/Q131607)
- Se usó Codex para implementar el prototipo, seleccionar fuentes, redactar relaciones y etiquetar el conjunto de desarrollo. La búsqueda y la evaluación consultan archivos locales.

## Recuperación de información

La búsqueda normaliza mayúsculas, tildes, puntuación y espacios. La coincidencia exacta tiene prioridad y favorece el nombre principal frente a un alias. Para consultas de dos o más palabras significativas, BM25 ordena los candidatos que contienen todas esas palabras en sus nombres, alias o nombres de referencia. La cobertura completa evita devolver, por ejemplo, leche condensada común al buscar una versión «sin azúcar». Cada palabra se indexa una vez por ficha. [Implementación de BM25 usada en el proyecto](https://github.com/dorianbrown/rank_bm25)

Cuando esas etapas no producen coincidencias, el buscador intenta completar prefijos y luego corregir uno o dos cambios según la longitud de la consulta, usando la distancia de Damerau-Levenshtein. La interfaz indica cuándo encontró palabras, completó un prefijo o corrigió una posible errata.

Las consultas con «para» o «per» pueden indicar un uso culinario, por ejemplo «chile poblano para rajas» o «amido di mais per addensare». El método completo recupera el ingrediente y busca relaciones con ese uso mediante un vocabulario bilingüe definido en `data/annotations.json`. Cuando el uso completo no se reconoce, la app muestra la ficha del ingrediente y omite las sugerencias. Las advertencias se etiquetan de forma distinta a las sustituciones.

## Evaluación

`data/evaluation.csv` registra 40 consultas de elaboración propia. Hay 36 consultas con ingrediente esperado, incluidas 14 de uso culinario, y cuatro que deberían quedar sin resultado. Cada consulta contextual tiene conjuntos esperados de sustitutos y advertencias, que pueden estar vacíos.

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
| Exacta | 27,8 % | 27,8 % | 100 % | 0 % |
| Exacta + difusa | 50,0 % | 50,0 % | 100 % | 0 % |
| BM25 + contexto | 97,2 % | 97,2 % | 100 % | 85,7 % |

El método completo falla en «¿Qué uso en vez de poblano en rajas?», una pregunta libre sin el patrón admitido. En «fécula de maíz para espesar una salsa sin gluten» sí recupera la fécula, pero se abstiene de sugerir un sustituto porque el uso incluye una restricción adicional que el vocabulario aún no interpreta. Las consultas y las etiquetas se diseñaron junto con el prototipo. Estas cifras describen el conjunto de desarrollo, y las cuatro abstenciones aportan evidencia limitada sobre consultas nuevas fuera del catálogo.

### Revisión culinaria

Para cada sustitución, una persona debe revisar si el destino cumple la función en el uso indicado y si las diferencias de sabor, textura o técnica son aceptables. Registra el resultado con `human_review` igual a `accepted` o `rejected` en la relación correspondiente de `data/annotations.json`, y reconstruye el catálogo. Las relaciones rechazadas se ocultan en la búsqueda y las fichas. La revisión documental de esta fase conserva las 15 propuestas pendientes de aceptación humana.
