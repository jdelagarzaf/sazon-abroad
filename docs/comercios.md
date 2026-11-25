# Activar la búsqueda de tiendas

Preparado el 24 de noviembre de 2026. Proveedor elegido: Tavily Search. Ciudad inicial: **Milano (Milán)**, editable en cada receta. La integración está implementada; falta una credencial para comprobar una consulta real desde la aplicación. Las pruebas HTTP simuladas no acreditan disponibilidad comercial.

## Opción gratuita recomendada

1. Abre [Tavily](https://app.tavily.com) y crea tu cuenta personalmente.
2. Conserva el plan **Researcher**: la [página oficial de precios](https://www.tavily.com/pricing) publica **1000 créditos al mes sin tarjeta**. No hace falta habilitar Pay As You Go ni introducir un medio de pago para esta entrega.
3. Copia una API key desde el dashboard. No la pegues en el chat ni la subas al repositorio.
4. Abre o crea `.env` en la raíz del proyecto. **Si ya existe, conserva su contenido.** Añade o actualiza una sola línea `TAVILY_API_KEY` con tu clave:

```dotenv
TAVILY_API_KEY=PEGA_TU_CLAVE_AQUI
SAZON_SEARCH_DAILY_LIMIT=25
```

5. Instala las dependencias y reinicia la aplicación:

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m flask --app app run
```

`app.py` carga `.env` automáticamente mediante `python-dotenv`; las variables existentes en la terminal tienen prioridad. `.env.example` es una referencia y no se carga. `.env` y sus variantes privadas están ignorados por Git. No hay que copiar ningún módulo nuevo ni modificar Python para activar la clave.

6. En otra terminal, comprueba la integración (máximo una búsqueda básica nueva; puede usar la caché):

```powershell
.\.venv\Scripts\python scripts/check_store_search.py --product "tortilla di mais" --city "Milano" --country "Italia"
```

El comando imprime estado, fecha y URL, nunca la clave. Si falta la credencial, devuelve código 1 sin consumir presupuesto. Después abre **Recetas → Pegar mi receta** o **Crear lista editable y buscar tiendas**, elige hasta ocho productos y pulsa **Buscar comercios en la web**.

## Opción para estudiantes

La [ayuda oficial para estudiantes](https://help.tavily.com/articles/6606514713-student-account) publica **cuatro meses del plan Project con 4000 créditos mensuales**, sujetos a verificar tu condición de estudiante. Indica contactar personalmente a soporte con el correo académico o una acreditación y canjear el cupón recibido en Billing. Comprueba con soporte la vigencia, los requisitos de facturación y qué sucede al terminar la promoción antes de cambiar de plan. El plan gratuito ordinario basta para probar este proyecto; el programa estudiantil es opcional. No se ha enviado ningún correo ni solicitado ninguna promoción en tu nombre.

Brave era el candidato inicial, pero su [documentación de facturación](https://api-dashboard.search.brave.com/documentation/resources/help-feedback) exige tarjeta para el crédito mensual. Se eligió Tavily por la preferencia de una opción gratuita sin tarjeta. Condiciones consultadas el 24 de noviembre de 2026; pueden cambiar.

## Uso y límites implementados

- HTTP nativo a `POST https://api.tavily.com/search`, autenticación Bearer. [Contrato oficial](https://docs.tavily.com/documentation/api-reference/endpoint/search).
- Solo búsqueda `basic`: **un crédito por búsqueda**, frente a dos para `advanced`, según la [guía de créditos](https://help.tavily.com/articles/8298987937-billing-credits-usage-limits). `auto_parameters` desactivado; sin respuestas generadas, imágenes, extracción de páginas ni llamadas adicionales.
- Caché persistente en `.runtime/stores.sqlite` durante 24 horas, separada por producto, ciudad, país, idioma y versión de consulta.
- Máximo **25 intentos nuevos al día UTC por instalación**, incluidos los intentos fallidos. Puedes reducirlo a 0–25 con `SAZON_SEARCH_DAILY_LIMIT`. No reintenta automáticamente las consultas fallidas. La caché sigue disponible al agotar el límite.
- Un máximo de 25 diarios equivale a 775 intentos en un mes de 31 días, por debajo de 1000 si esta instalación es el único consumidor de la cuenta. No controla el uso de otros proyectos ni sustituye el panel de Tavily. No habilita pagos ni modifica el plan.
- Tiempo máximo de 20 segundos por consulta, hasta cinco resultados. Una receta puede tardar más al buscar varios productos; se ejecuta en segundo plano.
- Solo se envían término local, ciudad y país; no se envía el texto completo de la receta ni las restricciones. Ollama sigue siendo la IA local de traducción.
- Los errores de autenticación, cuota, conexión, JSON o configuración conservan la receta. Los resultados parciales se conservan.

## Qué significa la evidencia

Un resultado incluye título, enlace, dominio, fragmento y fecha UTC. Se agrupa por dominio y se muestra para cuántos productos hay **enlaces candidatos**, junto con los productos sin consultar y las consultas sin resultados.

El proveedor busca la web; no constituye una API de inventario. Puede devolver un artículo editorial o un comercio que no vende ese producto. Por eso la interfaz conserva **producto por comprobar, stock desconocido y sucursal/envío por comprobar**, incluso si el título parece una página de producto. No etiqueta automáticamente ningún resultado como producto confirmado ni afirma que una tienda tenga toda la receta. La cobertura de productos verificados permanece en cero hasta contar con una comprobación independiente. Tampoco muestra precios inventados.

Los enlaces manuales son apoyo y no se cuentan como resultados de la integración. Las URL de resultados se filtran para esquemas HTTP/HTTPS, sin credenciales ni destinos privados literales; la aplicación no descarga páginas de comercios ni ejecuta su contenido.

## Comprobación pendiente al activar la clave

1. Ejecutar el comando de comprobación y guardar la fecha y las URL sin credenciales.
2. Hacer una búsqueda real desde una receta en Milán.
3. Revisar al menos 20 pares ingrediente–comercio: página pertinente, producto/presentación, sucursal o envío, enlace válido, stock conocido o desconocido.
4. Registrar la revisión en `docs/revision-comercios.csv`. Una revisión manual de una tienda no autoriza reutilizar su stock como dato permanente.

La ausencia de clave es el único requisito de activación del proveedor; obtenerla y aceptar los términos corresponde al titular de la cuenta.
