# Catálogo semántico México–Italia

## Fase 1 · Catálogo piloto y búsqueda

El piloto documenta diez ingredientes: queso Oaxaca, panela, Cotija, chile poblano, tomatillo, epazote, masa harina, piloncillo, nopales y guajillo. Cada propiedad publicada tiene una fuente. La búsqueda y el catálogo leen `data/catalog.json`; no necesitan consultar a Wikidata o un modelo para responder.

| Resultado | Cómo se representa |
| --- | --- |
| Mismo ingrediente | `name_it`: etiqueta o alias italiano del mismo concepto de Wikidata. |
| Cómo buscar el original | `reference_it` y `reference_kind`: nombre científico, término documentado o descripción. |
| Sustituto para un uso | Relación `culinary_substitute` con un `use`, un motivo, limitaciones y fuentes. |
| Sustituto con ajustes | La misma relación, con un campo `adaptation` separado para las instrucciones. |
| Sin sustituto registrado | Mensaje de abstención. Se puede documentar la razón por uso con `substitution_gaps`. Un falso equivalente específico tiene una relación `not_equivalent`. |

Para agregar una ficha, edita `data/ingredients.csv` y `data/annotations.json`. Las propiedades (`properties`) contienen `value` y una lista de identificadores `sources`. Los usos se identifican en `uses`, con alias en español e italiano. No registres como traducción un producto distinto que sirva como sustituto.

La búsqueda ordena las alternativas para el uso solicitado por revisión culinaria aceptada y respaldo directo, en ese orden. Los empates conservan el orden editorial. `evidence: direct` significa que la fuente respalda la alternativa para ese uso; si la fuente respalda propiedades pero la aplicación al plato es una inferencia, usa `inferred`. Para registrar la revisión culinaria, usa `human_review: accepted` o `rejected`; las sugerencias con fuentes y sin revisión aparecen como pendientes. Las rechazadas no se muestran.

Después de modificar las fuentes de datos, ejecuta `python scripts/fetch_data.py`. Para ofrecer un sustituto en una receta, registra también la cantidad y los pasos que cambian en esa receta.

## Fase 2 · Ampliación y propuestas por lotes

El grupo de ingredientes difíciles llega a 20. Se añadieron pasilla, morita, chile de árbol seco, chipotle en adobo, tostadas de maíz, elote tierno mexicano, jamaica seca, chayote, achiote y huitlacoche. Las recetas nuevas aprovechan esas fichas y las del piloto. El catálogo también incorpora maíz dulce como alternativa para esquites.

Ejecuta estos comandos desde la raíz del proyecto. El primero recupera candidatos por nombre en Wikidata y AGROVOC con sus etiquetas italianas, cuando las hay. El segundo prepara los pares, propiedades y fuentes. Puedes dar `origen:uso` para proponer destinos de la misma categoría, o `origen:destino:uso` para evaluar un destino concreto.

```powershell
python scripts/fetch_vocab.py maiz_dulce queso_oaxaca
python scripts/substitution_batch.py prepare chile_pasilla:sopa_azteca chipotle_adobo:tinga --output lote.json
python scripts/substitution_batch.py check lote.json data/substitution_drafts.json
```

Puedes usar el lote como entrada en un modelo y guardar su respuesta en JSON. Con `OPENAI_API_KEY` configurada, el comando `generate` también puede pedir las propuestas a un modelo compatible con salidas estructuradas. El valor de `--model` es el identificador del modelo habilitado en tu cuenta. [Referencia de la API Responses](https://developers.openai.com/api/reference/resources/responses/methods/create)

```powershell
python scripts/substitution_batch.py generate lote.json --model ID_DEL_MODELO --output propuestas.json
```

La comprobación verifica el formato, los pares, los usos y los IDs de fuentes. Revisa el respaldo culinario y la disponibilidad antes de incorporar una propuesta a `data/annotations.json`. Las propuestas de `data/substitution_drafts.json` esperan esa revisión. La aplicación consulta el catálogo generado.

## Fase 3 · Evaluación con consultas reservadas

La página **Evaluación** abre la comparación final. Puedes filtrar las consultas habituales o especializadas, cambiar de métrica e inspeccionar los errores de cada sistema. El conjunto de desarrollo sigue disponible en el selector. La [metodología](methodology.md#evaluación-final) describe las versiones, las métricas, los resultados y sus límites.
