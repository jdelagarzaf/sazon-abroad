# Sazón Abroad

Buscador de ingredientes para cocinar platillos mexicanos en Italia. El prototipo muestra nombres italianos, sustituciones para un uso concreto y advertencias cuando dos ingredientes cumplen funciones distintas.

## Ejecutar la aplicación

Requiere Python 3.12. En PowerShell, desde la carpeta del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m flask --app app run --debug
```

En macOS y Linux, usa `.venv/bin/python` en los dos últimos comandos. Abre <http://127.0.0.1:5000>. La app lee `data/catalog.json`, con 78 ingredientes del catálogo mexicano y 15 referencias italianas. En **Catálogo** puedes filtrar por categoría y estado, abrir la ficha o consultar la fuente.

## Adaptación con IA local

La nueva pantalla **Adaptar con IA** permite preguntas libres e ingredientes fuera del catálogo, con México → Italia como configuración inicial y otros trayectos experimentales. Usa un modelo local a través de Ollama y distingue el nombre del original de una sustitución por uso. Las propuestas se muestran pendientes de verificación culinaria.

Consulta la [guía de instalación, configuración y pruebas](docs/ia-local.md) y el [plan por fases](docs/plan-adaptacion-ia-local.md). El buscador documental, las recetas existentes y la evaluación histórica siguen disponibles.

## Recetas propias y tiendas

En **Recetas** puedes buscar por título, pegar una receta o crear un borrador de la versión elegida. Revisa cantidades, traduce ingredientes con IA local, elige sustituciones por uso y prepara una lista que agrupa cantidades compatibles. País, idiomas y ciudad son editables; Milán es el ejemplo inicial. Consulta [cómo usar las recetas propias](docs/recetas-libres.md).

La búsqueda web de comercios está preparada para **Tavily**, con caché y límites de uso. Para activarla solo hace falta añadir `TAVILY_API_KEY` a `.env` y reiniciar. La [guía de activación gratuita y opción para estudiantes](docs/comercios.md) explica cómo obtenerla. Los resultados son enlaces candidatos, con stock y envío por comprobar; todavía no hay una consulta real validada con una clave de este proyecto.

La [validación de la entrega](docs/validacion-final.md) separa las pruebas de software, la evaluación local y la revisión culinaria humana pendiente. No se afirma calidad universal ni disponibilidad comercial a partir de una salida generada.

## Editar la interfaz

Las fichas muestran nombres, ajustes y advertencias esenciales. Los motivos, propiedades, alias y fuentes se abren desde **Ver detalles** o **Detalles y fuentes**. La vista inicial ofrece hasta dos alternativas; los usos del mismo producto se agrupan en una tarjeta. Consulta el [registro de la fase de presentación](docs/fase-2-presentacion.md).

- `templates/base.html` define la estructura general y la navegación. Las otras plantillas en `templates/` contienen el HTML de cada página. `templates/components.html` contiene el buscador, las tarjetas y las listas de fuentes que comparten varias páginas.
- `assets/app.css` define la paleta en `@theme` y los estilos compartidos. Puedes usar clases de Tailwind directamente en las plantillas.
- `app.py` define las rutas y prepara los datos que recibe cada plantilla.

El CSS compilado se distribuye en `static/app.css`. Para regenerarlo después de cambiar estilos o clases de Tailwind, instala Node.js en tu entorno de desarrollo y ejecuta:

```sh
npm ci
npm run build:css
```

Durante el desarrollo puedes ejecutar `npm run watch:css` en otra terminal. Incluye el CSS regenerado al guardar los cambios en Git.

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
| `quesillo para quesadillas` | Scamorza y mozzarella con sus diferencias, ajustes y estado de revisión. |
| `tomatillo para salsa verde` | Sin sustituto registrado y una advertencia para no confundirlo con jitomate. |
| `zzzz` | Mensaje de búsqueda sin resultados. |

## Recetas mexicanas

En **Recetas** hay diez preparaciones, entre ellas quesadillas de quesillo, tostadas de tinga, esquites caldosos y sopa azteca. Puedes consultar la versión base o elegir alternativas para Italia. La lista de compras muestra el término italiano y la cantidad a usar. Los pasos se ajustan cuando eliges un sustituto.

Cada receta de `data/recipes.json` referencia ingredientes y usos del catálogo. Para añadir una alternativa, registra la relación y su fuente en `data/annotations.json`, y especifica en la receta la cantidad y cualquier cambio de preparación. Los pasos usan texto original de Sazón Abroad y cada ficha enlaza sus referencias culinarias y el crédito de su imagen.

## Fotos de los ingredientes

Las tarjetas cargan miniaturas desde Wikimedia Commons. El repositorio solo guarda las URL y los créditos en `data/photos.json`. Para incorporar las fotos de ingredientes nuevos o actualizar las referencias, ejecuta este comando después de regenerar el catálogo:

```powershell
python scripts/fetch_photos.py
```

El script consulta la propiedad P18 de Wikidata y guarda las miniaturas con una licencia compatible. Se pueden elegir archivos de Commons específicos cuando la foto de Wikidata muestra otra variedad o presentación, como un morrón rojo en la ficha donde se sugiere el verde. Las fichas sin foto conservan sus etiquetas, descripciones y fuentes culinarias.

## Evaluación

La sección **Evaluación** compara el catálogo base con el ampliado sobre 36 consultas finales. En **Desarrollo** están las 40 consultas de regresión. Puedes filtrar por dificultad e inspeccionar los resultados por consulta.

```powershell
.\.venv\Scripts\python evaluation.py --final
```

Las comprobaciones de regresión se ejecutan con `python -m unittest discover -s tests` en el entorno del proyecto.

Consulta las definiciones de las métricas, los límites del conjunto de desarrollo y cómo registrar la revisión culinaria en la [metodología](docs/methodology.md). El [plan del catálogo semántico](docs/semantic-catalog.md) explica cómo ampliar y revisar las fichas.

## Publicar la aplicación Flask

Usa un alojamiento que pueda ejecutar una aplicación web Python. Instala `requirements.txt` y configura este comando de arranque desde la raíz del repositorio:

```sh
waitress-serve --host=0.0.0.0 --port=8080 app:app
```

Si el proveedor asigna un puerto, usa ese valor en lugar de `8080`. El servidor entrega el CSS compilado desde `static/`, así que el alojamiento solo requiere Python. [Guía de despliegue de Flask](https://flask.palletsprojects.com/en/stable/deploying/)
