# Mi receta: tabla y modales

25 de noviembre de 2026.

El editor presenta ingredientes como texto en una tabla: nombre, cantidad original y propuesta elegida. El lápiz abre la edición de la fila; la cruz la elimina. El botón **+** abre el mismo formulario vacío para añadir un ingrediente. **Settings**, en el engranaje superior derecho, reúne título, países, ciudad, idiomas y restricciones.

El guardado ocurre dentro de cada modal. Cancelar, Escape o pulsar el fondo cierra el diálogo sin enviar cambios; el formulario se restaura al volver a abrir. Los diálogos nativos mantienen el foco y bloquean la interacción con el fondo. Un error de validación vuelve a abrir el formulario conservando sus campos.

**Enviar** genera propuestas para toda la receta. **Generar solo este** guarda los campos del modal y procesa únicamente esa fila; **Añadir y generar** crea primero el ingrediente y luego lo procesa. El progreso se muestra junto a la tabla, que permanece visible. Las propuestas se actualizan al terminar y las operaciones individuales reabren su modal.

Cuando hay platillo/función se solicita explícitamente una adaptación por uso. Si la respuesta devuelve sustitutos, se elige su primera alternativa; si devuelve identidad, se usa el término del original. No es una puntuación de calidad ni confirma disponibilidad comercial. El selector del modal permite cambiar de alternativa o conservar el original, con motivos, ajustes, límites y fuentes. La cantidad de un producto diferente no hereda la del original, y cambiar de alternativa vacía su cantidad en el formulario. Una regeneración conserva una cantidad introducida solo si la propuesta sigue siendo exactamente el mismo producto.

Los pasos originales permanecen siempre desplegados, con un lápiz para editarlos. Los ajustes esenciales de sustituciones siguen visibles; los motivos y la procedencia se consultan en el modal. La lista consolidada y la consulta de comercios mantienen su funcionamiento.

Se conservan protección CSRF, aislamiento por sesión, validación de revisiones y la cola de tareas. Si falla la cola después de añadir un ingrediente, se reabre la fila ya guardada para evitar duplicarla al reintentar.

Validación: 74 pruebas automáticas, incluyendo CRUD desde modales, opciones desconocidas, invalidación de propuestas, generación individual, selección automática, cantidades, pasos visibles y errores de cola. La guía de uso está en [recetas libres](recetas-libres.md).

La comprobación en navegador ejecutó la generación individual de queso Oaxaca para quesadillas con Ollama: se seleccionó mozzarella y quedó disponible scamorza. Se cambió la opción desde el modal, comprobando que no reutiliza la cantidad de otra alternativa. Enviar completó las otras filas. También se añadió una fila desde el modal con Enter, se comprobó cancelar/Escape en Settings y se revisó móvil a 390 × 844 sin desbordamiento horizontal. Los botones de guardar/generar permanecen visibles mientras se desplaza el contenido del modal.

Capturas: [tabla de escritorio](images/mi-receta-tabla.jpg), [modal de ingrediente](images/mi-receta-modal.jpg) y [móvil](images/mi-receta-movil.jpg). El cilantro de las capturas se añadió manualmente para comprobar el formulario; las otras tres propuestas proceden de la prueba de generación.
