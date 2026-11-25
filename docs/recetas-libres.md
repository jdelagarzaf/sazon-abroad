# Recetas propias y lista adaptada

La fase 3 añade `/mi-receta/nueva`, un espacio editable independiente del catálogo. Las diez recetas originales mantienen cantidades, opciones y pasos documentados. **Recetas** permite buscar por título e importar la versión elegida al nuevo espacio, incluyendo los ajustes esenciales de las sustituciones seleccionadas.

## Recorrido de demostración

1. Abre **Recetas → Pegar mi receta** y pega:

```text
Ensalada de pepino
Ingredientes
200 g de pepino
1 taza de yogur natural
Eneldo al gusto
Preparación
Corta el pepino y mezcla con el yogur.
Añade el eneldo.
```

2. Revisa los nombres y cantidades. El título de la receta se propone como uso inicial; abre **Uso y presentación** para precisarlo (rellenar, espesar, servir en frío…). Abre **Receta, destino e idiomas** para modificar país, idiomas, ciudad o restricciones. Milán (`Milano`) es el ejemplo inicial.
3. Pulsa **Guardar y traducir con IA local**. La página muestra el progreso y se actualiza al terminar. Puedes corregir el término local y guardar; se identifica como corrección propia.
4. Para sustituir, guarda el uso y pide una propuesta explícitamente en **Alternativas por uso**. Revisa ajuste y limitación, elige la propuesta e indica su cantidad. Sin una proporción comprobada se muestra **Por confirmar**, nunca se copia la cantidad original al sustituto.
5. Comprueba la lista y los cambios antes de cocinar. Consulta tiendas cuando hayas activado la clave siguiendo [la guía de comercios](comercios.md).

No hace falta dar de alta pepino, yogur o eneldo en `catalog.json`. Los términos generados siguen pendientes de revisión. No se declara seguridad para alergias a partir del nombre o del resultado del modelo.

## Extracción y cantidades

Se decidió usar extracción determinista y editable para cantidades y pasos, en lugar de pedirle al modelo que los reconstruya. Evita gastar inferencias e introducir cantidades que no aparecen en el original. La IA local se usa para traducir y proponer adaptaciones culinarias. Esta decisión reduce el alcance inicial de la extracción automática del plan: requiere **una línea por ingrediente** y los títulos **Ingredientes** y **Preparación/Instrucciones/Pasos/Elaboración**. Un párrafo libre debe separarse manualmente antes de continuar. No se importan páginas web arbitrarias.

El borrador conserva el texto pegado. Se reconocen cantidades iniciales, fracciones simples y mixtas y los calificadores explícitos «al gusto» y «cantidad necesaria». Las líneas ambiguas se conservan como texto editable. No se adivinan porciones, densidad, pesos por pieza ni cantidades ausentes. Límites: 6000 caracteres y 16 ingredientes; pasos editables hasta 6000 caracteres.

La consolidación suma fracciones exactas cuando producto, presentación y unidad coinciden. Convierte kg a g y l a ml; normaliza unidades de cucharas, tazas y piezas. No convierte tazas a gramos, cucharadas a mililitros ni números sin unidad a piezas. Cantidades con calificadores o desconocidas permanecen separadas. Cada compra conserva los ID de las filas que la originaron; esos ID pertenecen al documento, no al catálogo de alimentos.

## Pasos y sustituciones

Al importar una receta del repositorio se conservan los pasos de la versión elegida, sus cantidades comprobadas y sus ajustes. En recetas propias, los pasos mantienen el texto introducido. La vista **Cambios para cocinar** muestra cada original → sustituto, cantidad, ajuste y limitación junto a los pasos originales. No se declara una reescritura de técnicas validada: el usuario debe aplicar las correspondencias al cocinar. No se modifica silenciosamente una instrucción por una coincidencia parcial de palabras.

Cambiar país, idiomas, restricciones o ingredientes invalida las propuestas afectadas y la búsqueda de comercios. Cambiar solo la ciudad conserva las traducciones y descarta las búsquedas anteriores. La selección de un sustituto es independiente del término local del original.

## Persistencia y ejecución

Los borradores se guardan en `.runtime/recipes.sqlite`, fuera de Git, ligados a una sesión del navegador. Se pueden reabrir desde **Pegar mi receta → Tus borradores**. Otra sesión no puede abrirlos conociendo su URL. El secreto de sesión se crea localmente en `.runtime/session-secret` o se configura mediante `SAZON_SESSION_SECRET`. Borrar las cookies elimina el acceso; no es un sistema de cuentas, copia de seguridad o sincronización. La interfaz permite borrar un borrador cuando no tiene una tarea en curso.

Los formularios del espacio de recetas usan token CSRF y revisión de versión. Una edición antigua se rechaza en vez de sobrescribir cambios de otra pestaña. La cola admite una tarea activa y dos en espera por proceso. Las traducciones se hacen por ingrediente, con la caché existente; no se lanza una inferencia simultánea por cada alimento. Los errores preservan el borrador y las traducciones parciales ya guardadas. Reiniciar el servidor interrumpe la tarea y habilita reintentar.

Usar **un proceso** Flask/Waitress para esta entrega: la cola es local al proceso. No ejecutar múltiples workers sin trasladar la cola y su registro a un servicio compartido. La SQLite es almacenamiento de documentos/caché, no una base de equivalencias culinarias hardcoded.
