# Technical Debt and Bug Audit

**Fecha:** 2026-08-06
**Rama revisada:** `production`
**Commit revisado:** `529e923` (`Add 30-day rehire alerts`)
**Alcance:** servicios de aplicación, ingestión de fuentes, watcher, sincronización SQLite, webapp, seguridad, documentación y pruebas.

## Resumen ejecutivo

La aplicación tiene una base funcional sólida para un POC: separación entre evidencia de fuentes y empleados canónicos, workflow de aprobación, SQLite local/publicado, auditoría y pruebas de dominio. Sin embargo, todavía hay riesgos que pueden producir decisiones incorrectas sobre empleados o una operación difícil de recuperar.

Prioridades recomendadas:

1. Corregir el parsing de fechas de AccessNow antes de usar el rehire alert en producción.
2. Normalizar explícitamente `DEACTIVATED`; hoy puede terminar como empleado `ACTIVE` en el modelo canónico.
3. Reconciliar y expirar las notificaciones de rehire cuando el hold deja de aplicar.
4. Reemplazar la firma del watcher basada en `size + mtime` por checksum de contenido o una estrategia de observación más fuerte.
5. Añadir protección CSRF a todos los POST mutantes.
6. Hacer que el suite de pruebas sea verde y eliminar comandos/documentación obsoletos.

## Evidencia de validación

Comando ejecutado:

```text
.venv/bin/python -m pytest -q
```

Resultado actual:

```text
121 passed, 2 failed
```

Fallos observados:

- `tests/test_webapp.py::test_local_server_uses_loopback_and_ephemeral_port`: algunos entornos aislados impiden abrir el socket (`PermissionError: [Errno 1] Operation not permitted`); la prueba se omite únicamente en ese caso y debe ejecutarse en CI o entorno con loopback habilitado.

Los tests de fuente y empleados pasan, incluyendo la prueba del rehire alert agregada en `tests/test_source_updates.py`.

## Hallazgos priorizados

### [P1] REHIRE-001 — El alert interpreta mal las fechas reales de AccessNow

**Estado:** corregido en la rama `bugfix/technical-debt` con `application/source_date.py` y prueba de regresión en `tests/test_source_updates.py`.

**Evidencia:** `iam_automation/application/employee_service.py:148-158,220-223` solo acepta `date.fromisoformat()`. Los archivos reales de AccessNow contienen valores como `9/9/2025 6:07:00 AM PDT`.

**Impacto:** cuando `terminated_date` no es ISO, el sistema usa como fallback `access.created_at_utc`. El contador de días hábiles puede iniciar en la fecha de importación en lugar de la fecha de terminación real. Esto puede producir un falso bloqueo, liberar un caso demasiado pronto o mostrar una cantidad incorrecta de días restantes.

**Corrección recomendada:** crear un parser de fechas compartido para AccessNow/Roster Lock que soporte ISO, fechas US con hora, `AM/PM`, zonas `PST/PDT` y valores de Excel. Guardar además una fecha normalizada (`YYYY-MM-DD`) en el payload de evidencia y cubrir cada formato con pruebas.

### [P1] REHIRE-002 — `DEACTIVATED` no se conserva en el estado canónico

**Estado:** corregido en la rama `bugfix/technical-debt`; AccessNow normaliza aliases de desactivación, les da precedencia sobre `ACTIVE` y propaga el estado a employee y engagement. Regresión: `test_accessnow_deactivated_status_updates_worker_and_engagement`.

**Evidencia:** `iam_automation/application/accessnow_ingestion_service.py:163-165` deja `DEACTIVATED` como texto, pero `:253-262` convierte todo lo que no sea `TERMINATED` en `ACTIVE`.

**Impacto:** el alert puede detectar `DEACTIVATED` en el JSON, pero después de aplicar AccessNow el empleado y su engagement pueden quedar como `ACTIVE`. La fuente de verdad canónica contradice la evidencia de AccessNow y los filtros/reportes pueden tomar decisiones incorrectas.

**Flujo corregido:** el alert de 30 días es una validación crítica no bloqueante para la primera fase. Management puede enviar el cambio a la cola de aprobación; el hold y la evidencia roja permanecen visibles. La escritura canónica solo ocurre si la segunda fase aprueba la solicitud; si se deniega, no se reactiva ni se crea el engagement.

**Flujo implementado:** Roster Lock se conserva como evidencia aunque el caso genere alerta. Un administrador puede archivar la alerta con motivo; esto marca la observación como `RESOLVED`, conserva el registro y no modifica el estado del empleado. Los cambios de estado canónico permanecen bajo el adaptador de AccessNow/ServiceNow.

**Corrección recomendada:** definir un catálogo de estados (`ACTIVE`, `TERMINATED`, `DEACTIVATED`, etc.) y una función única de normalización usada por ingestión, alertas, reportes y UI. Añadir una prueba de aplicación de un registro `DEACTIVATED`.

### [P1] REHIRE-003 — El hold usa lunes-viernes, no días hábiles corporativos

**Estado:** corregido en `bugfix/technical-debt`; el cálculo excluye fines de semana y acepta un calendario explícito mediante `REHIRE_HOLIDAYS`.

**Evidencia:** `iam_automation/application/business_calendar.py` centraliza el cálculo y la lectura de fechas ISO configuradas.

**Impacto:** el resultado puede diferir de la política real si existen feriados de Estados Unidos, Costa Rica u otra región operativa. Un caso puede bloquearse o liberarse uno o varios días antes de lo permitido.

**Operación:** configurar `REHIRE_HOLIDAYS=2026-01-01,2026-07-04,2026-12-25` según la región aplicable. Si no se configura, el comportamiento es lunes-viernes; no se asumen feriados de Estados Unidos o Costa Rica sin una decisión operativa explícita.

### [P1] NOTIFY-001 — Las alertas críticas de rehire no se reconcilian ni expiran

**Estado:** corregido en `bugfix/technical-debt`; cada actualización reconcilia las notificaciones contra el conjunto actual de alerts, marca como `EXPIRED` las que ya no aplican y reactiva una alerta si reaparece.

**Evidencia:** `iam_automation/application/notification_service.py:165-210` crea una notificación determinista, pero no asigna `expires_at_utc` ni cambia el estado cuando el alert deja de existir. `EmployeeService.rehire_alerts()` solo se recalcula durante ciertas visitas o ciclos del watcher.

**Impacto:** una alerta puede seguir apareciendo en la banda superior después de que pasen los 30 días o después de que el Roster Lock sea superseded. El usuario puede ver un riesgo obsoleto y el contador de notificaciones no representa el estado actual.

**Corrección recomendada:** usar una clave de alerta estable, reconciliar alertas abiertas contra el conjunto actual en cada ingestión, resolver/expirar las que ya no aplican y asociar `expires_at_utc` al fin del hold cuando exista una fecha confiable.

### [P1] DATA-001 — El watcher puede no detectar un archivo reemplazado

**Estado:** corregido en `bugfix/technical-debt`; las observaciones ahora usan SHA-256 del contenido, evitando perder ediciones in-place con el mismo tamaño y timestamp.

**Evidencia:** `iam_automation/application/file_watch_service.py:257-261` construye la firma usando únicamente tamaño y `st_mtime_ns`.

**Impacto:** si OneDrive reemplaza el contenido conservando tamaño y timestamp de resolución similar, el cambio no se procesa. El sistema puede mantener evidencia y estados antiguos sin alerta.

**Corrección recomendada:** calcular SHA-256 del contenido para archivos pequeños/medianos, o usar checksum de contenido generado durante la ingestión como firma de observación. Mantener un mecanismo de debounce para no leer archivos todavía sincronizándose.

### [P1] SYNC-003 — Refresh podía reemplazar SQLite mientras el watcher lo leía

**Estado:** corregido en `bugfix/technical-debt`; `WorkspaceRefreshService`, `FileWatchService` y la lectura de versión comparten `WORKSPACE_IO_LOCK` durante operaciones de filesystem y SQLite.

**Impacto:** un refresh concurrente con el watcher podía producir lecturas inconsistentes del runtime local o un crash nativo del proceso en macOS (`SIGBUS`/`FS pagein error`).

**Regresión:** la suite completa debe ejecutarse en un entorno que permita abrir sockets; el flujo de aplicación pasa las pruebas de refresh y watcher.

**Nota adicional:** las escrituras automáticas del watcher actualizan el sidecar local únicamente si el runtime estaba limpio al comenzar el ciclo. Así no se vuelve a mostrar el mismo refresh como pendiente, pero tampoco se oculta una edición local real.

**Robustez adicional:** las lecturas de CSV/XLSX y checksums del watcher ahora requieren que tamaño y `mtime` permanezcan estables durante la lectura; si el archivo sigue sincronizándose, se reintenta y luego se deja para el siguiente ciclo.

### [P1] SEC-001 — No hay protección CSRF en formularios mutantes

**Estado:** corregido en `bugfix/technical-debt`; la aplicación crea un token por sesión, lo inyecta en formularios HTML y valida todos los `POST` de formulario. Los endpoints JSON requieren `X-CSRF-Token` si se consumen desde un navegador; el shutdown interno conserva su token de control independiente.

**Evidencia:** `iam_automation/webapp.py` genera, compara con tiempo constante y rechaza tokens ausentes o inválidos con HTTP 400.

**Impacto:** cualquier página visitada mientras existe una sesión puede intentar enviar acciones administrativas mediante el navegador. El riesgo es especialmente relevante para aprobar, publicar, restaurar, modificar usuarios o aplicar empleados.

**Corrección recomendada:** incorporar tokens CSRF por sesión/formulario, validar `Origin`/`Referer` como defensa adicional y cubrir todos los POST, incluyendo rutas de administración y logout/acciones de notificación.

### [P2] SYNC-001 — `WorkspaceVersion` no detecta modificaciones locales del SQLite

**Estado:** corregido en `bugfix/technical-debt`; el runtime local conserva un checksum base en un sidecar fuera de Git y ahora reporta modificaciones locales posteriores a la sincronización mediante `local_dirty`.

**Evidencia:** `iam_automation/application/workspace_refresh_service.py:65-76` usa el marcador `app_metadata.published_source_checksum` como `local_checksum`. Después de una edición local, el marcador puede seguir igual aunque el archivo SQLite haya cambiado.

**Impacto:** el dashboard puede indicar que no hay diferencia entre la copia publicada y la local cuando sí existen cambios locales. La publicación pendiente se maneja por otro marker, pero los dos estados pueden divergir y confundir al operador.

**Corrección recomendada:** separar explícitamente `published_source_checksum`, `local_content_checksum` y `publication_pending`. Calcular el hash real del SQLite local cuando se necesite comparar contenido y mostrar estados incompatibles como error operativo.

### [P2] SYNC-002 — El manifest puede bloquear el arranque después de cambios válidos

**Estado:** corregido en `bugfix/technical-debt`; además del diagnóstico accionable del preflight, existe una reparación explícita mediante `scripts/repair_runtime_manifest.py`. El comando valida la integridad SQLite antes de escribir el checksum y requiere `--confirm`.

**Evidencia:** `iam_automation/runtime_sync.py:88-116` rechaza el snapshot si el hash del SQLite no coincide con el manifest. Durante la revisión se reprodujo exactamente: el snapshot publicado cambió y el manifest quedó con el hash anterior.

**Impacto:** el preflight termina en `INVALID_PATH` y la aplicación no abre aunque el SQLite sea legible e íntegro. El diagnóstico original solo exponía “Local runtime SQLite synchronization: invalid”, sin resolver la causa en la interfaz.

**Operación:** `./.venv/bin/python scripts/repair_runtime_manifest.py /ruta/database/snapshots/iam_runtime.sqlite --confirm`. Nunca se regenera automáticamente sobre un archivo no validado.

### [P2] WATCH-001 — Excepciones del ciclo del watcher quedan fuera del flujo de recuperación

**Estado:** corregido en `bugfix/technical-debt`; además de separar errores operativos e inesperados, el límite del hilo cuenta fallos consecutivos, crea una alerta crítica después de tres ciclos y la resuelve automáticamente al recuperar un ciclo sano. La captura amplia permanece solo como barrera final del hilo.

**Evidencia:** `iam_automation/application/file_watch_service.py:322-326` captura cualquier `Exception`, registra log y continúa.

**Impacto:** el proceso permanece vivo aunque haya fallos repetidos de SQLite, permisos, corrupción o una regresión de código. Sin métrica, contador de fallos ni alerta administrativa, el usuario puede creer que el workspace está sincronizando cuando no lo está.

**Corrección recomendada:** registrar estado del último ciclo, número de fallos consecutivos, último error y timestamp; publicar una notificación crítica después de un umbral y pausar ingestas peligrosas hasta recuperación.

### [P2] DOC-001 — README referencia un script que no existe

**Estado:** corregido en `bugfix/technical-debt`; se agregó `scripts/create_access_database.py`, con modo `--show-schema` para macOS y modo de inicialización real para Windows/Access ODBC.

**Evidencia:** `README.md:23` y `README.md:92` invocan `scripts/create_access_database.py`, pero el archivo no existe en `scripts/`. El repositorio solo contiene `scripts/create_runtime_database.py` y utilidades relacionadas.

**Impacto:** una ruta documentada de bootstrap falla inmediatamente y puede llevar a crear o modificar bases de forma manual.

**Corrección recomendada:** corregir el comando, agregar el script faltante o marcar claramente el flujo como Windows/ODBC con la herramienta real (`scripts/create_runtime_database.py` o la guía de Access correspondiente).

### [P2] TEST-001 — El suite no está verde y una expectativa quedó obsoleta

**Estado:** corregido en `bugfix/technical-debt`; la expectativa usa el copy vigente y la prueba de Waitress se omite únicamente cuando el entorno niega loopback.

**Evidencia:** `.venv/bin/python -m pytest -q` queda verde en entornos sin permisos de socket, reportando el test como `skipped` en lugar de ocultar un fallo funcional.

**Impacto:** CI puede bloquear cambios por una expectativa que ya no representa el producto y por una prueba ambiental que no declara su requisito. Esto reduce confianza en el resultado global.

**Operación:** ejecutar la prueba en CI con loopback habilitado para validar el servidor real; en el sandbox local se conserva como prueba omitida por limitación ambiental.

### [P3] CODE-001 — Uso extendido de `except Exception` reduce la observabilidad

**Evidencia:** aparece en configuración, watcher, rutas administrativas, servicios de reportes, identidad y utilidades de archivos.

**Impacto:** errores de datos, permisos y programación se transforman en mensajes genéricos o se silencian. La recuperación y el diagnóstico dependen del log local.

**Corrección recomendada:** capturar excepciones específicas en los límites de dominio, conservar una excepción raíz con contexto, y devolver códigos/estados operativos diferenciados para UI, auditoría y retry.

## Deuda de diseño y mantenibilidad

- `EmployeeService` concentra consultas, reconciliación, parsing de payloads, alertas, promoción y construcción de vistas. Conviene separar `SourceEvidenceService`, `RehirePolicyService` y presenters de UI.
- El sistema tiene vocabularios de estado duplicados entre AccessNow, Worker, Engagement, Request e Ingestion. Un catálogo central evitaría conversiones silenciosas.
- La política de días hábiles está embebida en el servicio y no es configurable ni auditable por región.
- Parte de la UI está en inglés y parte en español; esto complica soporte y pruebas de copy.
- Las plantillas tienen bloques HTML muy extensos en una sola línea, lo que dificulta revisión, accesibilidad y cambios seguros.
- La carpeta raíz contiene artefactos locales (`runtime.sqlite`, WAL, backups, logs y `.DS_Store`); aunque varios están ignorados, conviene separar explícitamente `workspace/` de la fuente.
- Hay 32 archivos de prueba para una base de aproximadamente 11k líneas de Python; falta una matriz de pruebas de ingestión con formatos reales, concurrencia y fallos de filesystem.

## Plan recomendado

### Antes del siguiente release

1. Parser de fechas compartido y catálogo de estados.
2. Reconciliación/expiración de rehire alerts.
3. Suite verde: corregir expectativa del watcher y aislar el test de sockets.
4. Agregar pruebas de `DEACTIVATED`, fechas AccessNow reales, feriados y expiración.
5. Corregir README y registrar la causa específica del fallo de sync en preflight.

### Siguiente iteración

1. CSRF y configuración explícita de cookies/sesión.
2. Checksum de contenido para el watcher.
3. Estado de salud del watcher visible en Control Center.
4. Comparación real entre SQLite local y snapshot publicado.
5. Separación de servicios de dominio y presentadores de UI.

### Antes de producción

1. Pruebas de recuperación para cada punto del workflow de publicación.
2. Calendario de feriados aprobado por negocio.
3. Revisión de permisos sobre SharePoint/OneDrive y backups.
4. Pruebas de carga para los métodos que deserializan miles de filas.
5. Threat model actualizado y revisión de seguridad independiente.

## Criterio de cierre

La deuda no debe considerarse cerrada hasta que:

- `pytest` termine sin fallos en el entorno soportado.
- Exista una prueba de regresión para cada hallazgo P1.
- Los estados y fechas de fuentes queden normalizados antes de entrar al modelo canónico.
- Las alertas críticas tengan ciclo de vida explícito.
- El preflight explique exactamente cómo recuperar un manifest inválido o una sincronización fallida.
