# Informe de navegación del dashboard

**Fecha:** 30 de septiembre de 2026 (hora local, America/Costa_Rica)
**Aplicación:** `http://127.0.0.1:49914`
**Punto de entrada:** `/dashboard`
**Método:** recorrido visual en Safari con la sesión local existente. Se abrió cada página enlazada desde la navegación y se revisaron el título, el encabezado principal y el contenido accesible para detectar 404, errores del servidor o páginas vacías por fallo.

## Resultado

No encontré páginas rotas ni enlaces de navegación que terminaran en 404 durante el recorrido. Las **37 rutas** de la lista siguiente cargaron una página reconocible con su título y contenido; esto es una comprobación de navegación manual, no una prueba automatizada de cada interacción de formulario.

## Páginas recorridas

| Área | Rutas |
|---|---|
| Workspace | `/dashboard`, `/profile`, `/requests`, `/requests/new`, `/help/testing`, `/help/employees`, `/help/business-rules`, `/bug-reports` |
| Operaciones y empleados | `/employees`, `/employees/source-updates`, `/employees/duplicates`, `/admin/approvals`, `/admin/imports`, `/admin/quarantine`, `/admin/publication`, `/admin/templates`, `/admin/delegations` |
| Reportes | `/reports`, `/reports/vendors`, `/reports/duplicates`, `/reports/new-hires`, `/reports/terminations`, `/reports/studio` |
| Administración y gobernanza | `/admin`, `/admin/users`, `/admin/governance`, `/admin/master/temporary-super-operator`, `/admin/master/administrators`, `/admin/master/settings`, `/admin/master/audit`, `/admin/windows-identities`, `/admin/ingestion-sources`, `/admin/ingestion-sources/library`, `/admin/business-rules`, `/admin/business-rules/config`, `/engine/dashboard`, `/notifications` |

## Hallazgos

### 1. El watcher no tiene una plantilla Object activa

**Página:** `/employees/source-updates` y estado relacionado en `/engine/dashboard`
**Severidad:** Alta para la operación de ingesta; no es un fallo de navegación.

La pantalla de actualizaciones muestra `Latest watcher error: No approved Object Template is active.` La biblioteca de plantillas (`/admin/ingestion-sources/library`) cargó, pero muestra el Object como `Not configured`. La configuración de fuentes (`/admin/ingestion-sources`) también carga y se identifica como borrador: `No watcher · No activation`.

**Impacto observado:** las páginas abren, pero el watcher no dispone de una plantilla Object aprobada para procesar los archivos que dependen de esa configuración. Hay que revisar el ciclo de configuración/aprobación de plantilla antes de esperar ingesta automática para esa fuente.

### 2. Referencias a puertos locales antiguos en reportes de bugs

**Página:** `/bug-reports`
**Severidad:** Baja; no son enlaces de navegación activos.

Algunos reportes existentes muestran como texto URLs de instancias anteriores, entre ellas `127.0.0.1:52557` y `127.0.0.1:58938`. Las cadenas aparecen como contenido de los reportes, no como enlaces HTML del dashboard; por tanto no las conté como enlaces rotos de la aplicación. Si alguien las copia manualmente, podrían apuntar a instancias que ya no están ejecutándose.

## Alcance y límites

- Las páginas y rutas visibles desde los menús, el centro de control y la biblioteca de reportes se abrieron y cargaron. No se observó una respuesta 404 ni una página de error del servidor.
- No envié formularios, cargué archivos, cambié configuración, aprobé elementos ni publiqué datos.
- No abrí enlaces de acción asociados a un registro individual cuando podían cambiar su estado (por ejemplo, abrir una notificación relacionada), ni ejecuté exportaciones que descargan datos. Los destinos con identificadores y los enlaces de filtros con query string no se validaron uno por uno.
- Los estados sin datos o sin configuración que aparecen en algunas pantallas se registran como tales; no los clasifiqué como páginas rotas.

## Conclusión

La navegación principal del dashboard funciona en la sesión revisada. El asunto que requiere seguimiento es la falta de una plantilla Object aprobada y activa para el watcher. No se confirmaron enlaces internos rotos en las rutas recorridas.
