# IA local: primera fase

La pantalla **Adaptar con IA** (`/adaptar`) procesa ingredientes y preguntas libres con Ollama. El catálogo México–Italia sigue disponible en **Búsqueda** y aporta contexto documental cuando coincide con el trayecto y los idiomas solicitados. Las recetas y la evaluación histórica conservan su funcionamiento.

## Ejecutar

Desde la raíz del proyecto, con Python 3.12:

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
```

Instala [Ollama para Windows](https://docs.ollama.com/windows) o utiliza su distribución portátil oficial. Inicia el servicio local en otra terminal si todavía no está activo:

```powershell
$env:OLLAMA_NO_CLOUD = "1"
ollama serve
```

Descarga el modelo una sola vez y arranca Flask:

```powershell
ollama pull qwen2.5:3b
.\.venv\Scripts\python -m flask --app app run
```

Abre <http://127.0.0.1:5000/adaptar>. La primera consulta carga el modelo; las siguientes pueden ser más rápidas. La descarga del modelo necesita conexión; la inferencia posterior se ejecuta localmente. Las fotografías externas del resto de la aplicación conservan sus URL habituales.

### Distribución portátil en este checkout

Si la preparación de esta fase dejó Ollama en `.runtime/ollama/`, no hace falta instalarlo globalmente. En una primera terminal:

```powershell
$env:OLLAMA_MODELS = Join-Path $PWD ".runtime/models"
$env:OLLAMA_NO_CLOUD = "1"
& .\.runtime\ollama\ollama.exe serve
```

En otra terminal, descarga el modelo si aún no existe:

```powershell
& .\.runtime\ollama\ollama.exe pull qwen2.5:3b
```

Arranca Flask como se indica arriba. `.runtime/` contiene binarios, modelos y resultados locales de prueba; está excluido de Git. No forma parte de la aplicación distribuida. Ollama puede crear sus claves y registros de usuario en sus directorios habituales; el modelo portátil se guarda en la ruta definida por `OLLAMA_MODELS`.

## Configuración

`.env.example` documenta las variables. **Flask no carga ese archivo automáticamente**; define las variables en la terminal que arranca la aplicación o mediante la configuración de tu alojamiento.

| Variable | Valor inicial | Función |
| --- | --- | --- |
| `SAZON_OLLAMA_URL` | `http://127.0.0.1:11434` | Servicio Ollama; solo HTTP de loopback, sin rutas ni credenciales. |
| `SAZON_OLLAMA_MODEL` | `qwen2.5:3b` | Modelo instalado; se rechazan identificadores que contengan `cloud`. |
| `SAZON_OLLAMA_TIMEOUT` | `120` | Espera de transporte, entre 1 y 180 segundos. |
| `SAZON_OLLAMA_CONTEXT` | `4096` | Límite de contexto, entre 2048 y 32768 tokens. |
| `SAZON_OLLAMA_OUTPUT_TOKENS` | `1200` | Límite de salida, entre 256 y 4096 tokens. |

La configuración inicial usa `qwen2.5:3b` Instruct. Las variantes Qwen3 probadas introdujeron problemas de configuración de razonamiento, latencia o salidas incorrectas al forzar su desactivación; esas pruebas no permiten concluir que un tamaño concreto sea mejor de manera general. No se adopta una plantilla personalizada para forzar el cierre del razonamiento. El cliente consulta `/api/show`, respeta los modos anunciados y lee únicamente el contenido final, sin presentar razonamiento intermedio. Se puede cambiar el modelo con `SAZON_OLLAMA_MODEL`, repitiendo las pruebas de calidad y latencia.

Para ampliar el tiempo de espera en equipos con CPU lenta:

```powershell
$env:SAZON_OLLAMA_TIMEOUT = "180"
.\.venv\Scripts\python -m flask --app app run
```

El endpoint se configura en el servidor, nunca desde el formulario. No se usan proxies del sistema ni redirecciones para inferencia, y no hay fallback a una API remota. Mantén `OLLAMA_NO_CLOUD=1` en el servicio y usa modelos descargados localmente. La aplicación web y Ollama deben ejecutarse en el mismo equipo; el navegador puede estar en otro, pero «este equipo» se refiere al servidor de la aplicación.

## Consultas y contrato

- Consulta libre hasta 500 caracteres; no requiere un ID del catálogo.
- País e idioma se indican por separado. México, Italia, `es`, `it` y explicación en `es` son los valores iniciales.
- Uso, presentación y restricciones son opcionales; el modelo puede pedir aclaración si falta contexto para sustituir.
- Al cambiar de país, comprueba también el idioma de los nombres locales en **Idiomas y presentación**. Cambiar el país no adivina qué idioma prefieres.
- Otros trayectos son experimentales. El contenido editorial México–Italia no se reutiliza como respaldo de otros trayectos.

`local_name` siempre describe el ingrediente original. Los productos distintos van en `alternatives`, con uso, motivo, ajuste y limitación. El resultado distingue identidad, descripción, sustitución y abstención. El esquema de generación separa estos modos para evitar combinaciones contradictorias. La validación del servidor rechaza propiedades adicionales, textos fuera de límites, URLs generadas, IDs de fuentes desconocidos, alternativas duplicadas, confusión entre original y sustituto y sustituciones sin uso declarado. Una pregunta pendiente implica abstención y ninguna alternativa. No puede demostrar por sí sola que una recomendación sea correcta ni que respete una alergia.

Las fuentes se recuperan mediante IDs de los datos locales y sus URL las aporta el servidor. Una comprobación adicional rechaza coincidencias de nombres con relaciones de no equivalencia documentadas para el ingrediente y uso reconocidos. Es una protección limitada a los nombres recuperados, no una verificación semántica completa. Toda propuesta generada se etiqueta como pendiente de verificación, incluso si cita una referencia. No se genera stock, tiendas ni precios en esta fase.

Las consultas que solo piden un nombre ya documentado conservan ese par de identidad y no reciben usos ni sustituciones no solicitados. Las advertencias documentales se entregan al modelo en una lista distinta de los sustitutos disponibles, para evitar que las copie como recomendaciones. Una entrada nueva puede usar el conocimiento general del modelo sin inventar referencias.

Las consultas breves de nombre, sin uso, presentación ni restricciones, generan únicamente `local_name`; el servidor compone el resto de la ficha. Esto reduce latencia y evita prosa innecesaria. La detección inicial usa patrones de pregunta y conectores comunes; otros patrones siguen la ruta completa de adaptación y requieren evaluación adicional.

Para un uso reconocido con opciones documentadas y sin restricciones expresas, el esquema limita la selección a esos candidatos. Las notas españolas de una opción seleccionada se conservan desde las referencias, incluyendo la ausencia de un ajuste registrado. Si el modelo presenta el término documentado del original como su propio sustituto, se reclasifica como nombre del original. Los ingredientes y usos sin esas opciones conservan la generación abierta, siempre pendiente de verificación. Las restricciones expresas desactivan esa selección cerrada y la sustitución de las notas del modelo por las notas generales.

## Caché y fallos

La caché reside en memoria, dura una hora y conserva como máximo 128 consultas por proceso. Su clave incluye contexto completo, restricciones, presentación, países, idiomas, ciudad, modelo, parámetros, versión del prompt y evidencia documental. Se pierde al reiniciar; no incorpora propuestas al catálogo. Los fallos no se cachean.

La inferencia se solicita con un POST explícito. Cargar `/adaptar` no llama al modelo. Si falta el servicio o el modelo, el formulario conserva la consulta. Las respuestas HTTP diferencian entrada inválida (400), salida inválida (502), servicio/modelo/configuración no disponible (503) y timeout (504). El usuario puede reintentar o abrir el buscador documental.

## Comprobar

Pruebas automáticas sin descargar un modelo:

```powershell
.\.venv\Scripts\python -m unittest discover -s tests
```

Prueba real del servidor y modelo instalados:

```powershell
.\.venv\Scripts\python scripts/check_local_ai.py --output .runtime/local-ai-smoke.json
.\.venv\Scripts\python scripts/check_local_ai.py --query "hojas de curry" --destination Alemania --target-language de --output .runtime/local-ai-germany.json
```

El script devuelve código 1 si falla alguna consulta y guarda las respuestas, el modelo, la versión de prompt y el tiempo de servicio. El tiempo incluye carga cuando corresponda; no es una medición p95. No usa la caché de Flask ni acredita aceptación culinaria. Revisar manualmente las respuestas guardadas antes de mostrarlas como ejemplos correctos.

Para depurar una salida rechazada, añade `--diagnostics --output .runtime/diagnostico.json`. Ese archivo local incluirá la respuesta rechazada y el motivo técnico; no se muestran en la interfaz ni se incorporan al catálogo.

## Alcance y siguientes fases

Esta fase introduce contratos neutrales, transporte Ollama, contexto documental sencillo, validación, caché y una pantalla funcional. No incluye fine-tuning, embeddings ni base vectorial. Quedan después: simplificación de las fichas heredadas, extracción de recetas nuevas, búsqueda de comercios y evaluación culinaria reservada. Las metas de calidad y latencia del plan siguen siendo objetivos hasta medirlas con el protocolo completo.

El [registro de validación de la fase 1](fase-1-validacion.md) contiene las pruebas reales y los errores de conocimiento observados. La validez de JSON no garantiza una traducción correcta. Los destinos adicionales son experimentales.

Referencias: [API de chat de Ollama](https://docs.ollama.com/api/chat), [salidas estructuradas](https://docs.ollama.com/capabilities/structured-outputs), [distribución Windows](https://docs.ollama.com/windows), [Qwen2.5 3B y sus capacidades de instrucciones y JSON](https://ollama.com/library/qwen2.5:3b).
