# Validación de las fases de recetas y comercios

La entrega implementa el recorrido local receta → ingredientes revisables → términos locales/alternativas → lista de compra → consulta de comercios. La aceptación culinaria y la comprobación de tiendas reales son verificaciones independientes; no se sustituyen por pruebas de software.

## Reproducir las comprobaciones

Desde la raíz del proyecto:

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m unittest discover -s tests -v
npm ci
npm run build:css
git diff --check
```

La suite comprueba regresión de búsqueda/recetas, estructura de las respuestas, fuentes inventadas, caché, errores de Ollama, avisos esenciales visibles, extracción y cantidades exactas, separación de cantidades de sustitutos, aislamiento de borradores, CSRF, revisiones antiguas, reinicios, protocolo Tavily, errores de autenticación/cuota, URL, escape HTML y presupuesto persistente. Los tests del proveedor usan HTTP simulado y nunca consumen créditos.

## Conjunto reservado y medición real

`data/local_ai_reserved.json` congela 40 consultas México → Italia (identidad, usos, restricciones, ingredientes nuevos y ambigüedad/abstención), diez México → Alemania y cinco recetas. Se excluyeron las consultas de humo y de la demostración usadas para ajustar la fase 1. Las etiquetas nominales son orientativas y provisionales; no equivalen a aprobación humana. No se han retocado los prompts usando las respuestas de este conjunto.

Con Ollama disponible, ejecuta:

```powershell
.\.venv\Scripts\python -X utf8 scripts/evaluate_local_ai.py --translate-recipes
```

El script compara `hybrid` (modelo con referencias recuperadas) y `model_only` (mismo modelo, prompt y parámetros, sin alimentos ni relaciones en el contexto). Cada consulta usa un servicio de caché nuevo. Se mide por separado la repetición con caché. El informe incluye hash del conjunto, modelo/configuración, prompt, consultas, respuestas publicadas, errores rechazados, tiempos y revisión humana nula. Se guarda tras cada consulta para poder reanudar; rechaza mezclar otro conjunto, prompt o configuración en el mismo informe. Usa `--output` para un nuevo experimento. No ejecutes otras inferencias a la vez si quieres comparar latencias.

El buscador documental se registra como línea base separada: puede recuperar fichas, pero no genera equivalencias alemanas ni comprende restricciones generales. No se le asigna una puntuación culinaria comparable a la generación. La evaluación histórica permanece intacta.

Las cinco recetas comprueban extracción, cantidades originales, consolidación, pasos y, con `--translate-recipes`, traducciones reales. La conservación de una cantidad no demuestra que la traducción o una técnica sean correctas. No hay sustituciones automáticas en estas recetas reservadas.

La nueva pantalla **Evaluación → Evaluación separada de IA local** presenta el informe de `docs/local-ai-results.json`. Los resultados medidos se completan al final de este documento.

## Revisión humana pendiente

```powershell
.\.venv\Scripts\python scripts/export_local_review.py
```

Este comando crea `docs/revision-culinaria.csv` con respuestas y campos de revisión vacíos; rechaza sobrescribir una revisión existente. Un revisor debe contrastar identidad, función, ajustes, restricciones, abstención y fuentes, consignando nombre y fecha. Los errores deben mantenerse como errores, no eliminarse del denominador. No rellenar `accepted` a partir de coincidencias de texto o autoevaluación del modelo.

El objetivo del plan de al menos 80 % de aceptación culinaria **no se declara alcanzado sin esta revisión**. Las restricciones críticas siguen necesitando atención humana; el programa no certifica seguridad alimentaria.

## Comercios

No se dispone de `TAVILY_API_KEY`. Se comprobó el estado sin clave sin consumir presupuesto y se probaron peticiones/respuestas simuladas. Sigue [comercios.md](comercios.md) para crear la cuenta gratuita, pegar la clave y ejecutar una búsqueda real. Después registra al menos 20 pares en `docs/revision-comercios.csv`; las 20 filas vacías son una plantilla, **cero pares revisados**.

No se han inventado tiendas, precios, stock ni resultados para rellenar la demostración. Los enlaces manuales no cuentan como integración operativa. Activar la cuenta y obtener la clave son pasos del titular; el código ya está listo para recibirla.

## Decisión sobre RAG

No se ha añadido una base vectorial. Las referencias locales se recuperan con el buscador existente. La comparación automática permite inspeccionar el efecto del contexto, pero sin aceptación culinaria humana no acredita el umbral de diez puntos propuesto para justificar RAG. Se conserva la arquitectura sencilla y la posibilidad de añadir fuentes cuando los errores medidos lo justifiquen.

## Resultados de esta ejecución

Fecha: 24 de noviembre de 2026. **67 pruebas correctas**, dependencias consistentes y CSS compilado. El conjunto reservado tiene SHA-256 `96c96f263fa785962a2a77b6d34260204974b5601e81a812b31dc371df16d5bd`.

Configuración seleccionada: `gemma3:4b`, prompt `culinary-v11`, contexto 4096, máximo 1200 tokens de salida, timeout 120 s, CPU; Ollama 0.40.18. Digest del modelo: `68ceab7e468a31c988b44d5a4984a0e21f58c4f7158c6ce29c1804babac38df7`. Ollama informó **2 888 784 936 bytes residentes**, VRAM 0. Eso no representa la memoria total de Python, navegador y sistema.

| Variante actual | Intentos | Publicadas válidas | Errores rechazados | p50 | p95 | Coincidencia nominal provisional |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemma con referencias | 50 | 50 | 0 | 6,49 s | 27,11 s | 28/30 |
| Gemma sin referencias | 50 | 49 | 1 | 1,07 s | 17,78 s | 18/30 |

Las latencias incluyen consultas nominales y contextuales, sin caché de aplicación, y errores; no son percentiles de un único tipo de consulta. El objetivo p95 ≤15 s **no se cumple**. Se usa ejecución en segundo plano para recetas. La comparación con/sin referencias mantiene modelo, prompt y parámetros; no convierte los diez aciertos nominales adicionales en mejora de aceptación culinaria.

El cronómetro de esta medición fue `GetTickCount64()` mediante `time.monotonic`, con resolución anunciada de 15,625 ms. Sus repeticiones de caché registraron cero al quedar por debajo de esa resolución; **no significan tiempo instantáneo**. Una prueba adicional con `QueryPerformanceCounter`, después de descargar el modelo de memoria, midió para «pepino»: **5,30 s en frío, 0,83 s en caliente sin caché de aplicación y 1,68 ms con caché**. Es un caso de desarrollo, no otro p95. Para reproducir esa comprobación:

```powershell
ollama stop gemma3:4b
.\.venv\Scripts\python -X utf8 scripts/measure_local_startup.py
```

Si usas la distribución portátil, sustituye `ollama` por `.\.runtime\ollama\ollama.exe`. El script distingue modelo ya cargado de arranque en frío y guarda configuración, digest, memoria y tiempos en `.runtime/startup-probe.json`.

Las **cinco recetas reservadas** se procesaron con inferencia local real, sin errores de transporte/validación y conservando sus cantidades y pasos. Se comprobó la suma de las dos entradas de lentejas compatibles. Esto no aprueba las traducciones generadas ni evalúa cambios de técnica para sustitutos.

La [salida completa seleccionada](local-ai-results.json) contiene las 100 ejecuciones, cinco recetas, línea base documental y prueba de arranque/caché. Se conserva además el [informe inicial Qwen](local-ai-qwen25-results.json): 49/50 respuestas publicadas por variante y coincidencia nominal 20/30 con referencias, 3/30 sin ellas. Algunos tiempos iniciales coincidieron con pruebas de desarrollo. Entre ese informe y el actual cambiaron **modelo y tratamiento de nombres nuevos**, por lo que no es una comparación aislada de tamaños de modelo.

Persisten errores semánticos: Gemma produjo `Cucurbita varietà Bottae` para chayote y `Linsen` para garbanzo en alemán. Son resultados que necesitan corrección, no ejemplos aceptados. Las referencias del catálogo identifican [chayote como Sechium edule](https://www.wikidata.org/wiki/Q319611) y [garbanzo como Cicer arietinum](https://www.wikidata.org/wiki/Q81375); un esquema válido no impide confundir especies. El conjunto se mantiene congelado y no se reajustó el prompt con estas salidas. La revisión de restricciones y utilidad culinaria permanece pendiente.

La inspección visual comprobó importación de la receta elegida, cantidades originales y seleccionadas, avisos esenciales, navegación por teclado, progreso local, estado sin clave y acceso a la guía. También se ejecutó la receta de desarrollo con pepino, yogur natural y eneldo desde el formulario: Gemma mostró `cetriolo`, `yogurt naturale` y `Aneto`, conservando 200 g, una taza y «al gusto», sin añadir alimentos al catálogo. No se usaron correcciones manuales para esa captura. En móvil de 390 × 844, el documento ocupó 375 px de ancho, sin desbordamiento horizontal. Capturas: [lista generada en escritorio](images/fase-3-escritorio.jpg), [editor móvil](images/fase-3-movil.jpg) y [lista y comercios en móvil](images/fase-4-movil.jpg). La búsqueda comercial real y los 20 pares siguen pendientes; se han revisado **cero** pares comerciales.
