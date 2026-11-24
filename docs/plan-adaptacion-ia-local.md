# Plan preliminar: adaptación culinaria con IA local

Fecha: 24 de noviembre de 2026. Estado: propuesta previa a implementación.

## Objetivo

Evolucionar Sazón Abroad hacia una herramienta que adapte ingredientes y recetas entre países, empezando por México → Italia. La adaptación debe considerar la función del ingrediente en el plato, no solo traducir su nombre. El resultado principal será una lista de compra localizada, con alternativas comprensibles y enlaces a comercios encontrados en la web.

La primera entrega validará el enfoque con un modelo pequeño ejecutado localmente. La arquitectura admitirá otros países e idiomas; eso no significa prometer calidad universal antes de evaluarlos.

## Punto de partida revisado

- Flask y Jinja sirven la aplicación; Tailwind define sus estilos. No hace falta cambiar de framework.
- `search.py` resuelve nombres, erratas y usos mediante el catálogo y vocabularios español–italiano. No interpreta de forma general preguntas libres.
- `data/catalog.json` contiene 93 fichas; sus fuentes, relaciones y advertencias son útiles como referencia, pero actualmente delimitan qué puede responder la aplicación.
- `recipe_plans.py` y `data/recipes.json` ya permiten preparar listas y cambiar pasos en diez recetas. Las recetas dependen de IDs y alternativas del catálogo.
- `templates/find_components.html` presenta motivos, ajustes y limitaciones en varios bloques visibles. Ya hay desplegables de fuentes que se pueden aprovechar.
- `scripts/substitution_batch.py` genera propuestas por lotes con una API remota opcional; no constituye inferencia local integrada en las consultas.
- No hay integración de búsqueda comercial. La evaluación actual mide recuperación sobre el catálogo, no calidad de generación ni disponibilidad en tiendas.

Hay modificaciones previas en el repositorio. La implementación deberá conservarlas y trabajar sobre el estado actual sin restaurar archivos.

## Decisiones propuestas

### 1. Modelo local para comprender y adaptar

Usar Ollama como servidor local y un adaptador Python independiente de las rutas Flask. Candidato inicial: `qwen3:4b`, cuantizado; comparar con `qwen3:1.7b` si el equipo necesita una opción menor. La elección final dependerá de pruebas de español, italiano, adaptación culinaria y latencia en el equipo de demostración.

La ficha de Ollama publica un archivo de aproximadamente 2,5 GB para `qwen3:4b`; ese tamaño no equivale a la RAM necesaria durante la ejecución. Aún falta verificar RAM, GPU y tiempos reales. No se instalará ni descargará nada como parte de este documento.

El modelo recibirá ingrediente, presentación, receta o uso, países, idiomas y restricciones. Devolverá JSON con un esquema validado por el servidor:

- Nombre local para buscar el original, cuando pueda identificarlo.
- Tipo: mismo ingrediente, término descriptivo, sustituto para ese uso o sin propuesta suficiente.
- Hasta dos alternativas, un ajuste esencial y una limitación breve.
- Estado de evidencia: referencia disponible o propuesta generada pendiente de verificación.
- Ambigüedades que requieran una aclaración.

El esquema controla el formato, no la veracidad. No se presentará la autoconfianza del modelo como probabilidad de acierto. Las fuentes deberán proceder de referencias recuperadas por la aplicación; el modelo no podrá inventar URLs ni declarar validación humana.

Separar identidad de sustitución: «poblano» no se traduce como «peperone verde» aunque este pueda servir para rellenar. El contexto importa: una propuesta para rellenar no se reutiliza automáticamente en rajas. Respetar restricciones expresas y pedir contexto o abstenerse cuando falte información decisiva.

Configurar modelo, endpoint, límites de contexto, tiempos máximos y versión de prompt. Cachear por entrada, países, idiomas, uso, restricciones y versión de modelo/prompt. Las explicaciones ampliadas se generan solo al solicitarlas y no deben cambiar silenciosamente la alternativa elegida.

Si Ollama falla, mostrar un estado recuperable y permitir consultar los resultados documentados existentes. No reemplazarlo silenciosamente por una API de IA remota.

### 2. El catálogo deja de ser el límite del sistema

Conservar el catálogo como respaldo documental, casos de regresión y ejemplos revisables. Permitir entradas nuevas en texto libre sin exigir un ID existente. Separar los datos editoriales de la caché de respuestas generadas.

Consultar las referencias locales pertinentes y entregarlas como contexto cuando existan. Esto es recuperación sencilla de evidencia; no requiere inicialmente embeddings, una base vectorial ni un corpus mundial de alimentos.

**Decisión inicial: no construir RAG vectorial.** Reconsiderarlo únicamente si los errores medidos se deben a conocimiento documental faltante y un pequeño experimento mejora al menos 10 puntos porcentuales la aceptación culinaria frente al modelo sin recuperación, sobre los mismos casos reservados y con latencia aceptable. Ese umbral es una propuesta de decisión, no un resultado obtenido. Si no aporta esa mejora, mantener el enfoque sencillo y documentar sus límites.

### 3. Países e idiomas como parámetros

Definir un contexto común con `origin_country`, `destination_country`, `source_language`, `target_language`, `ui_language`, `city` opcional y restricciones. País e idioma son campos separados. México → Italia será el valor inicial.

Los nuevos contratos usarán nombres neutrales como `original_name`, `local_name`, `culinary_use`, `preparation`, `quantity` y `unit`. Un adaptador leerá los campos heredados `name_es`, `name_it` y `reference_it` mientras se migra la interfaz. No habrá una matriz manual de equivalencias por cada par de países.

Verificar la extensibilidad con un segundo trayecto, por ejemplo México → Alemania, en una prueba pequeña independiente. Marcar otros trayectos como experimentales hasta validarlos.

### 4. Interfaz compacta y con detalle bajo demanda

La tarjeta cerrada mostrará nombre original → término local, tipo de resultado, una recomendación principal y, cuando sea esencial, un ajuste o advertencia de una línea. Máximo dos alternativas por defecto.

Usar «Ver detalles» para motivos, diferencias y ajustes completos, y «Fuentes» para evidencia y procedencia. Reservar «Explicar esta alternativa» para ampliar con IA bajo demanda; no generar texto adicional al abrir cada ficha. Mantener visibles las restricciones críticas y la indicación breve de propuesta no verificada.

Reutilizar desplegables accesibles, navegación por teclado y estados de carga/error. Revisar móvil y escritorio. La vista inicial debería permitir entender qué comprar sin leer varios párrafos.

### 5. Receta → lista adaptada → tiendas

Primero aprovechar las diez recetas actuales e incorporar búsqueda por título. Añadir entrada de receta pegada por el usuario para no depender exclusivamente de las recetas del repositorio. El modelo extraerá ingredientes, cantidades, unidades y función culinaria; el usuario podrá corregir la extracción antes de adaptar.

No inventar cantidades ausentes. Conservar el original y marcar cantidades desconocidas. Mostrar cambios de técnica cuando una sustitución los requiera y mantener lista y pasos coherentes. Las recetas actuales conservarán sus pasos documentados; los cambios generados se distinguirán de ellos.

La lista resultante agrupará ingredientes repetidos cuando las unidades sean compatibles, permitirá conservar el original o elegir alternativa y registrará qué ingrediente corresponde a cada compra. No se intentará generar un catálogo ilimitado de recetas ni importar arbitrariamente cualquier web en la primera entrega.

### 6. Búsqueda web para comercios

Crear una interfaz `StoreSearchProvider` y un primer proveedor de búsqueda web, con Brave Search API como candidato. Antes de integrarlo, comprobar credenciales disponibles, condiciones y coste vigente. No depender de las herramientas de búsqueda de esta conversación para ejecutar la aplicación.

Usar país, ciudad o código postal introducido por el usuario y términos locales para buscar páginas de productos y comercios. Distinguir compra física de venta online y comprobar cobertura de envío cuando la fuente lo indique. Empezar con una ciudad italiana de demostración configurable.

Cada resultado incluirá comercio, URL, ingrediente relacionado, tipo de evidencia y fecha de consulta. Distinguir:

- Producto encontrado en una página del comercio.
- Comercio candidato, sin producto confirmado.
- Disponibilidad o stock desconocidos.

Un resultado de búsqueda o una página de producto no prueba stock actual en una sucursal. Mostrar cobertura «N de M ingredientes con evidencia» y faltantes; nunca afirmar que una tienda tiene toda la receta sin evidencia para cada ingrediente.

Agrupar consultas, deduplicar productos y dominios, limitar peticiones y cachear con caducidad. Aplicar tiempos máximos y manejar cuotas y fallos. Si se leen páginas, restringir la extracción a URLs públicas válidas y tratar su contenido como datos, no como instrucciones para el modelo.

El buscador aporta enlaces reales; el modelo puede ayudar a clasificar su pertinencia, pero no generar comercios, precios o stock como hechos. Si falta una clave o no hay resultados, informar el estado y ofrecer enlaces de búsqueda manual como apoyo, sin contarlos como integración completada.

**Precios fuera del requisito inicial.** Mostrarlos solo cuando haya precio publicado, moneda, presentación y fecha. No deducir un total de receta si faltan productos o conversiones fiables.

## Fases y entregables

| Fase | Trabajo | Criterio de salida |
| --- | --- | --- |
| 0. Línea base | Ejecutar pruebas actuales; registrar pantallas y casos; verificar equipo y servicios disponibles. | Estado previo reproducible y configuración de demostración identificada. |
| 1. IA local, prioridad principal | Contratos neutrales, adaptador Ollama, JSON validado, preguntas libres, caché y estados de error. | Resolver ingredientes nuevos sin editar el catálogo; diferenciar traducción y sustitución por uso. |
| 2. Presentación | Tarjetas compactas, detalles y explicación bajo demanda. | Una recomendación comprensible en la vista cerrada; avisos esenciales visibles y detalle accesible. |
| 3. Recetas | Búsqueda en recetas existentes, entrada de texto, extracción editable y lista adaptada. | Receta ajena al catálogo procesada sin alta manual de cada ingrediente; cantidades y cambios trazables. |
| 4. Comercios | Proveedor web real, ubicación, evidencia y agrupación por tienda. | Lista con enlaces reales, cobertura y faltantes; errores y falta de stock tratados explícitamente. |
| 5. Validación y entrega | Comparación, revisión culinaria, segundo trayecto, documentación y demo. | Resultados medidos, límites publicados e instalación local reproducible. |

Implementar por entregas pequeñas. No migrar todo el catálogo ni incorporar precios, fine-tuning, agentes autónomos o una base vectorial antes de validar el recorrido principal.

## Mapa de implementación previsto

- Mantener `search.py` como buscador documental y línea base de evaluación.
- Añadir módulos separados para contratos de adaptación, cliente local, orquestación y búsqueda comercial; nombres definitivos al implementar.
- Integrar esos servicios desde `app.py`, con acciones explícitas para generación y búsqueda externa.
- Extender `recipe_plans.py` para ingredientes no catalogados sin romper las recetas existentes.
- Simplificar `templates/find_components.html`, `templates/find.html`, `templates/components.html` y `templates/recipes.html`; actualizar `assets/app.css` y regenerar `static/app.css` si cambian estilos.
- Añadir configuración de ejemplo sin secretos, instrucciones de Ollama y documentación del proveedor comercial.
- Mantener la evaluación histórica intacta; añadir una evaluación específica de la nueva arquitectura y actualizar `docs/methodology.md` con sus resultados reales.

## Evaluación propuesta

Crear antes de ajustar prompts un conjunto reservado de al menos 40 casos México → Italia: identidad, sustitución por función, preguntas libres, ingredientes ausentes del catálogo, ambigüedad, restricciones y abstención. Añadir cinco recetas no usadas durante el desarrollo y diez casos del segundo trayecto.

Comparar buscador actual, modelo local sin contexto documental y modelo con contexto local sencillo. Evaluar con revisión humana: identidad correcta, utilidad culinaria, ajuste necesario, respeto de restricciones, abstención y procedencia. No comparar porcentajes nuevos directamente con el benchmark histórico si cambia la tarea o el conjunto.

Objetivos iniciales propuestos, sujetos a registrar resultados: al menos 80 % de aceptación culinaria en el conjunto nuevo; 100 % de respuestas publicadas con esquema válido; ninguna restricción crítica conocida ignorada. Una salida inválida debe rechazarse o mostrarse como error, no publicarse como resultado. No declarar alcanzadas estas metas sin revisión.

Medir latencia p50/p95, memoria y arranque en frío, con y sin caché. Objetivo provisional: p95 de adaptación de un ingrediente ≤ 15 segundos en caliente en el equipo de demo. Si no se cumple, comparar modelo menor, reducir contexto y usar ejecución en segundo plano para recetas.

Para tiendas, revisar manualmente al menos 20 pares ingrediente–comercio y medir pertinencia del producto, ubicación/envío, cobertura y enlaces válidos. Registrar fecha y respuestas de ejemplo para reproducir pruebas sin red; comprobar por separado una búsqueda real. Una prueba con respuestas simuladas no acredita integración operativa.

Ejecutar regresión existente y pruebas nuevas relevantes: validación de JSON, tiempos máximos, ausencia de modelo o clave, referencias falsas, restricciones y coherencia entre lista y pasos. Revisar visualmente móvil, teclado, desplegables y estados de espera.

## Primera demostración esperada

Elegir México → Italia y una ciudad; buscar una receta existente o pegar otra; corregir ingredientes si hace falta; obtener términos locales y alternativas por función mediante IA local; elegir sustituciones; consultar tiendas; abrir detalles solo cuando se necesiten.

Incluir tres casos explicables: jitomate como identidad, poblano con propuestas distintas según el plato y masa harina para tortillas como caso donde no debe sugerirse polenta como equivalente directo. Añadir un ingrediente nuevo y un ejemplo del segundo trayecto para demostrar que el catálogo y el par México–Italia ya no son límites estructurales.

## Dependencias y decisiones pendientes

- Verificar hardware y seleccionar modelo mediante medición, no por tamaño de descarga.
- Elegir ciudad inicial; mientras no se defina, mantenerla configurable y pedirla al consultar tiendas.
- Obtener una credencial válida del proveedor web y comprobar su coste antes de llamadas de pago.
- Conseguir revisión culinaria humana para afirmar aceptación; las propuestas generadas no la sustituyen.
- Para publicar, el servidor Flask deberá tener acceso a un proceso Ollama y memoria suficiente. Una instalación de Ollama en el portátil no queda disponible automáticamente para un alojamiento remoto.

## Referencias técnicas consultadas

Consultadas el 24 de noviembre de 2026. Sustentan la viabilidad técnica; no prueban la calidad culinaria del modelo.

- [Ollama: salidas estructuradas y validación con esquema](https://docs.ollama.com/capabilities/structured-outputs).
- [Ollama: ficha de Qwen3 4B, cuantización y tamaño del archivo](https://ollama.com/library/qwen3:4b).
- [Ollama: variantes de Qwen3](https://ollama.com/library/qwen3).
- [Brave Search API: búsqueda web, contexto local y parámetros de país e idioma](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started).
