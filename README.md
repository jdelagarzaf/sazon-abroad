# Sazón Abroad

Buscador de ingredientes para cocinar platillos mexicanos en Italia. El prototipo muestra nombres italianos, sustituciones para un uso concreto y advertencias cuando dos ingredientes cumplen funciones distintas.

## Ejecutar la aplicación

Requiere Python 3.12. En PowerShell, desde la carpeta del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m streamlit run app.py
```

En macOS y Linux, usa `.venv/bin/python` en los dos últimos comandos. Streamlit indica la URL local. La app lee `data/catalog.json`, con 59 ingredientes del catálogo mexicano y ocho referencias italianas. En **Catálogo** puedes filtrar por categoría y estado, abrir la ficha o consultar la fuente.

## Regenerar el catálogo

```powershell
python scripts/fetch_data.py
```

Ese comando usa `data/wikidata_snapshot.json` y se puede ejecutar sin conexión. `data/ingredients.csv` contiene los ingredientes y alias seleccionados y `data/annotations.json` contiene las notas con fuentes y las relaciones culinarias. El script comprueba los nombres italianos elegidos contra las etiquetas y alias, elimina alias repetidos dentro de cada idioma de una ficha y detecta conceptos duplicados.

Para descargar revisiones vigentes y regenerar ambos archivos:

```powershell
python scripts/fetch_data.py --refresh
```

Cada ficha basada en Wikidata enlaza al concepto y a la revisión consultada. Wikidata ofrece sus datos estructurados bajo CC0. [Acceso a los datos de Wikidata](https://www.wikidata.org/wiki/Wikidata:Data_access/en)

## Demo

| Consulta | Qué debe mostrar |
| --- | --- |
| `jitomate` o `pomodoro` | Jitomate → pomodoro, con el enlace al concepto en Wikidata. |
| `jitomtae` | Jitomate como coincidencia aproximada. |
| `cilantro fresco` | Coriandolo, con una nota que distingue las hojas frescas de las semillas. |
| `dolce patata` | Camote → patata dolce mediante búsqueda por palabras con BM25. |
| `cuaresmeno` | Chile jalapeño mediante un alias sin tilde. |
| `leche condensada sin azúcar` | Sin coincidencia para esa presentación. |
| `chile poblano` | Peperone verde como propuesta de sustitución para rellenar, con sus limitaciones y el estado de revisión. |
| `chile poblano para rajas` | Solo la propuesta para rajas, con sus límites de sabor. |
| `amido di mais per addensare` | Alternativas para espesar, con una advertencia de gluten para la harina de trigo. |
| `masa harina` | Qué término buscar en el envase y por qué la polenta no sirve como reemplazo directo en tortillas. |
| `zzzz` | Mensaje de búsqueda sin resultados. |

## Recetas mexicanas

En **Recetas** están el guacamole con jitomate, las rajas con crema y los chilaquiles verdes. Puedes consultar la versión base o elegir alternativas para Italia. La lista de compras muestra el término italiano y la cantidad a usar. Los pasos se ajustan cuando eliges un sustituto.

Cada receta de `data/recipes.json` referencia ingredientes y usos del catálogo. Para añadir una alternativa, registra la relación y su fuente en `data/annotations.json`, y especifica en la receta la cantidad y cualquier cambio de preparación. Los pasos usan texto original de Sazón Abroad y cada ficha enlaza sus referencias culinarias y el crédito de su imagen.

## Fotos de los ingredientes

Las tarjetas cargan miniaturas desde Wikimedia Commons. El repositorio solo guarda las URL y los créditos en `data/photos.json`. Para incorporar las fotos de ingredientes nuevos o actualizar las referencias, ejecuta este comando después de regenerar el catálogo:

```powershell
python scripts/fetch_photos.py
```

El script consulta la propiedad P18 de Wikidata y guarda las miniaturas con una licencia compatible. Se pueden elegir archivos de Commons específicos cuando la foto de Wikidata muestra otra variedad o presentación, como un morrón rojo en la ficha donde se sugiere el verde. Las fichas sin foto conservan sus etiquetas, descripciones y fuentes culinarias.

## Evaluación

La sección **Evaluación** del menú lateral compara tres métodos sobre 40 consultas y permite filtrar errores. Puedes reproducir las métricas y los resultados por consulta desde PowerShell:

```powershell
.\.venv\Scripts\python evaluation.py
```

Las comprobaciones de regresión se ejecutan con `python -m unittest discover -s tests` en el entorno del proyecto.

Consulta las definiciones de las métricas, los límites del conjunto de desarrollo y cómo registrar la revisión culinaria en la [metodología](docs/methodology.md).

## Publicar en Streamlit Community Cloud

Con el código en un repositorio público de GitHub y la cuenta vinculada, crea la aplicación eligiendo la rama que contiene la entrega y `app.py` como archivo principal. Selecciona Python 3.12 en *Advanced settings* y prueba las consultas de la tabla desde la URL pública. [Guía de despliegue de Streamlit](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
