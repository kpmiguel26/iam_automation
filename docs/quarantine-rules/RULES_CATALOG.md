# Quarantine rules catalog

El identificador `RL-001`, `MR-001`, etc. es la referencia de este catÃ¡logo.
El nombre que se guarda lo arma el Guided rule builder con esta convenciÃ³n:

```text
<PHASE> - <REPORT_CODE> - <NUMBER> - <FIELD> - <DESCRIPTIVE_NAME>
```

Ejemplo: `BEFORE - RL - 001 - email - Employee email is missing`.
El cÃ³digo del reporte se calcula desde el nombre del reporte; no se mantiene
una lista de cÃ³digos quemada en el catÃ¡logo ni en el cÃ³digo.

Catálogo de reglas para recrear después de limpiar `runtime.sqlite`.

La interfaz de reglas crea inicialmente las reglas como `DRAFT`. Después de
revisar la condición hay que activarlas desde **Business rules**.

## Importante: alcance por fuente

Las reglas se evalúan después de guardar la ingesta y sus findings aparecen en
**Quarantine**. En la implementación actual, las reglas `BEFORE` se evalúan
sobre el lote staged ya comprometido, antes de ejecutar la fase `AFTER`; no se
ejecutan antes de que el adapter lea o persista el archivo. Las reglas `AFTER`
se evalúan después de guardar los hechos en SQLite.

El wizard permite seleccionar `All reports` o una fuente concreta. Las reglas
marcadas como **Compartida** pueden usar `All reports`; las reglas marcadas como
**Específica** deben seleccionar su reporte para evitar marcar como ausente un
campo que simplemente no pertenece a otra fuente.

## Comportamiento en fase 1

`BEFORE` y `AFTER` no son bloqueantes. Una regla `BEFORE` detecta la coincidencia
después de que el adaptador crea y compromete el lote staged, y la enlaza al
lote antes de la evaluación `AFTER`; una regla `AFTER` detecta la coincidencia
directamente sobre los hechos persistidos. Una infracción nunca cancela la
importación ni deshace los datos recibidos.

`fact_quarantine` es la consulta maestra de cuarentena: cada fila enlaza el
lote, el registro de origen, el empleado cuando ya fue identificado, la regla,
el campo afectado, el valor observado y la severidad. `rule_findings` se
mantiene como detalle técnico y compatibilidad del registro de evaluación.

Por eso un empleado puede continuar dentro del flujo de recepción aunque tenga
una o varias infracciones abiertas. El badge de cuarentena y cualquier decisión
operativa quedan para una fase posterior.

## Configuración actual para la prueba

Para probar la ejecución temprana del orquestador, todas las reglas de este
catálogo se crearán temporalmente con phase `BEFORE`. Esto no las convierte en
bloqueantes: una coincidencia solamente genera la infracción en
`fact_quarantine` y la importación continúa.

## Procedimiento para probar una regla

1. Abrir **Administration -> Business rules** y seleccionar **Create a rule**.
2. Elegir `BEFORE` para probar la fila normalizada, o `AFTER` para probar los
   hechos ya guardados en SQLite.
3. Seleccionar el reporte indicado en **Fuente objetivo**. Para reglas
   especÃ­ficas no usar `All reports`.
4. Completar field, operator y value exactamente como aparecen en la regla.
5. Completar el nÃºmero y el nombre descriptivo. Confirmar el preview con el
   formato `PHASE - CODE - NUMBER - FIELD - NAME`.
6. Crear la regla como `DRAFT` y presionar **Test** en el catÃ¡logo. La prueba
   muestra los registros que hacen match, pero no activa la regla ni crea
   findings.
7. Si el resultado es correcto, presionar **Activate** y revisar los findings
   en **Quarantine**.

Si la prueba muestra cero matches, revisar el batch local, el scope, el texto
normalizado del value y el operador elegido. **Test** tambiÃ©n funciona sobre
reglas `DRAFT`, para validar la condiciÃ³n antes de activarla.

## Reglas compartidas para Roster Lock y Master Roster

Estas son las primeras reglas recomendadas para probar el flujo completo.

### RL-MR-001 — Employee email is missing

- **Fuente objetivo:** Roster Lock y Master Roster
- **Tipo:** Compartida
- **Phase:** `BEFORE`
- **Field:** `email`
- **Operator:** `missing`
- **Value:** dejar vacío
- **Severity:** `WARNING`
- **Descripción:** Employee records without an email require review before downstream matching or access work.

Esta regla utiliza un campo común a ambas fuentes y puede crearse ahora.

### RL-MR-002 — Terminated assignment requires review

- **Fuente objetivo:** Roster Lock y Master Roster
- **Tipo:** Compartida
- **Phase:** `BEFORE`
- **Field:** `assignment_status`
- **Operator:** `equals`
- **Value:** `TERMINATED`
- **Severity:** `WARNING`
- **Descripción:** Review records marked as terminated before they are used in operational workflows.

El valor debe coincidir con el texto normalizado que entregue el archivo. Si el
origen usa otro valor, por ejemplo `TERM`, hay que crear una regla adicional o
normalizar ese estado antes de evaluarlo.

## Reglas específicas de Roster Lock

Campos confirmados para Roster Lock:

`vendor_employee_id`, `vendor_name`, `first_name`, `last_name`, `email`,
`job_title`, `supervisor_name`, `onboarding_date`, `production_start_date`,
`assignment_status` y `work_order_id`.

### RL-003 — Vendor employee ID is missing

- **Fuente objetivo:** Roster Lock
- **Tipo:** Específica — requiere scope `ROSTER_LOCK`
- **Phase:** `BEFORE`
- **Field:** `vendor_employee_id`
- **Operator:** `missing`
- **Value:** dejar vacío
- **Severity:** `ERROR`
- **Descripción:** Roster Lock rows must have a vendor employee ID to be reconciled.

### RL-004 — Vendor name is missing

- **Fuente objetivo:** Roster Lock
- **Tipo:** Específica — requiere scope `ROSTER_LOCK`
- **Phase:** `BEFORE`
- **Field:** `vendor_name`
- **Operator:** `missing`
- **Value:** dejar vacío
- **Severity:** `ERROR`
- **Descripción:** Roster Lock rows without a vendor name cannot be safely classified.

### RL-005 — Work order is missing

- **Fuente objetivo:** Roster Lock
- **Tipo:** Específica — requiere scope `ROSTER_LOCK`
- **Phase:** `BEFORE`
- **Field:** `work_order_id`
- **Operator:** `missing`
- **Value:** dejar vacío
- **Severity:** `WARNING`
- **Descripción:** Review Roster Lock assignments without a work order reference.

## Reglas específicas de Master Roster

Campos confirmados para Master Roster:

`employee_number`, `employee_name`, `first_name`, `last_name`, `email`,
`nuid_login_id`, `npn_login_id`, `parent_client`, `client`, `program`,
`project`, `site_hr_location`, `supervisor_employee_number`,
`supervisor_name`, `job_code`, `job_title`, `hire_date`, `project_start_date`,
`production_start_date`, `actual_termination_date`, `term_reason`,
`assignment_status` y `user_principal_name`.

### MR-003 — NUID login ID is missing

- **Fuente objetivo:** Master Roster
- **Tipo:** Específica — requiere scope `MASTER_ROSTER`
- **Phase:** `BEFORE`
- **Field:** `nuid_login_id`
- **Operator:** `missing`
- **Value:** dejar vacío
- **Severity:** `WARNING`
- **Descripción:** Master Roster records without a NUID login ID require identity review.

### MR-004 — Employee number is missing

- **Fuente objetivo:** Master Roster
- **Tipo:** Específica — la validación de ingesta ya cubre este caso
- **Phase:** `BEFORE`
- **Field:** `employee_number`
- **Operator:** `missing`
- **Value:** dejar vacío
- **Severity:** `ERROR`
- **Descripción:** Master Roster records must have an Employee Number.

Esta regla es redundante con la validación de entrada actual. Se documenta para
referencia, pero no es necesario activarla mientras la cuarentena de ingesta ya
esté cubriendo ese error.

### MR-005 — Composite NPN value requires review

- **Fuente objetivo:** Master Roster
- **Tipo:** Específica — seleccionar el reporte `MASTER_ROSTER`
- **Phase:** `BEFORE`
- **Field:** `npn_login_id`
- **Operator:** `contains`
- **Value:** `|RECORD|`
- **Severity:** `WARNING`
- **Descripción:** Review Master Roster NPN values that contain a composite `NPN|RECORD|value` identifier.

El wizard ahora permite seleccionar el reporte `Master Roster`, filtra sus
fields y ofrece el operador `contains`. Estos valores se conservan además como
evidencia de origen y deben revisarse desde Quarantine.

## Orden recomendado para recrearlas

Durante la prueba, usar primero el botÃ³n **Test** sobre cada regla `DRAFT` y
activar solamente las reglas cuyo resultado sea el esperado. DespuÃ©s de
activar, revisar los findings creados en **Quarantine**.

1. Crear `RL-MR-001 — Employee email is missing` y usar **Test** antes de activar.
2. Crear `RL-MR-002 — Terminated assignment requires review` y usar **Test** antes de activar.
3. En las reglas específicas, seleccionar primero el reporte correspondiente
   (`Roster Lock` o `Master Roster`) para que el wizard limite los fields.
4. Usar **Test** en cada regla y revisar los registros que hicieron match.
5. Activar solamente las reglas validadas y revisar los resultados en **Quarantine**, verificando regla, empleado, campo
   afectado y valor observado.

## Registro de recreación

### Nombres finales esperados en el registry

| Referencia | Scope a seleccionar | Nombre generado esperado |
|---|---|---|
| RL-MR-001 para Roster Lock | `ROSTER_LOCK` | `BEFORE - RL - 001 - email - Employee email is missing` |
| RL-MR-001 para Master Roster | `MASTER_ROSTER` | `BEFORE - MR - 001 - email - Employee email is missing` |
| RL-MR-002 para Roster Lock | `ROSTER_LOCK` | `BEFORE - RL - 002 - assignment_status - Terminated assignment requires review` |
| RL-MR-002 para Master Roster | `MASTER_ROSTER` | `BEFORE - MR - 002 - assignment_status - Terminated assignment requires review` |
| RL-003 | `ROSTER_LOCK` | `BEFORE - RL - 003 - vendor_employee_id - Vendor employee ID is missing` |
| RL-004 | `ROSTER_LOCK` | `BEFORE - RL - 004 - vendor_name - Vendor name is missing` |
| RL-005 | `ROSTER_LOCK` | `BEFORE - RL - 005 - work_order_id - Work order is missing` |
| MR-003 | `MASTER_ROSTER` | `BEFORE - MR - 003 - nuid_login_id - NUID login ID is missing` |
| MR-004 | `MASTER_ROSTER` | `BEFORE - MR - 004 - employee_number - Employee number is missing` |
| MR-005 | `MASTER_ROSTER` | `BEFORE - MR - 005 - npn_login_id - Composite NPN value requires review` |

Para reglas compartidas se recomienda crear una variante por reporte. AsÃ­ el
scope evita evaluar como `missing` un field que no existe en otra fuente.

| Rule ID | Nombre | Phase | Field | Operator | Severity | Estado |
|---|---|---|---|---|---|---|
| RL-MR-001 | Employee email is missing | BEFORE | `email` | `missing` | WARNING | Pendiente |
| RL-MR-002 | Terminated assignment requires review | BEFORE | `assignment_status` | `equals` | WARNING | Pendiente |
| RL-003 | Vendor employee ID is missing | BEFORE | `vendor_employee_id` | `missing` | ERROR | Bloqueada por scope |
| RL-004 | Vendor name is missing | BEFORE | `vendor_name` | `missing` | ERROR | Bloqueada por scope |
| RL-005 | Work order is missing | BEFORE | `work_order_id` | `missing` | WARNING | Bloqueada por scope |
| MR-003 | NUID login ID is missing | BEFORE | `nuid_login_id` | `missing` | WARNING | Pendiente |
| MR-004 | Employee number is missing | BEFORE | `employee_number` | `missing` | ERROR | Cubierta por validación |
| MR-005 | Composite NPN value requires review | BEFORE | `npn_login_id` | `contains` | WARNING | Pendiente |

## Auditoría de rule evaluation y backlog de hoy

**Revisión:** 2026-09-10. Esta sección registra el estado del trabajo de
evaluación después de implementar la comparación explícita de
`left operand + operator + right operand`. No cambia el alcance de fase 1:
las reglas siguen siendo advisory, no bloquean la ingesta y no escriben en
plataformas autoritativas.

### Estado confirmado en el código

- **Implementado:** `ConditionEvaluator` acepta el contrato explícito con
  operandos `field`, `literal` y `derived`, además del contrato legado
  `field/operator/value`.
- **Implementado:** operadores allow-listed `exists`, `missing`, `equals`,
  `not_equals`, `contains`, `in`, `greater_than`, `less_than`, `between`,
  `before` y `after`.
- **Implementado:** composición con `all`, `any` y `not`; la validación
  rechaza operadores, operandos y funciones derivadas no permitidos.
- **Implementado:** el derivado `business_days_between` usa el calendario y
  la versión de contexto fijados para la regla.
- **Implementado:** `create_complex_rule` valida el árbol y persiste una
  versión en estado `DRAFT`; la evaluación `BEFORE` y `AFTER` conserva el
  comportamiento no bloqueante.
- **Cubierto por pruebas:** forma legado, forma explícita compuesta,
  calendario/feriados, operador no permitido, scope por reporte, persistencia
  de findings y preview de reglas `DRAFT`.

### Hallazgos de la auditoría

1. **El motor está por delante de la interfaz.** El wizard guiado y sus rutas
   siguen creando solo condiciones legado y exponen seis operadores:
   `exists`, `missing`, `equals`, `not_equals`, `contains` e `in`. No permiten
   construir desde la UI `left/right`, grupos, comparaciones entre campos ni
   `greater_than`/`less_than`/`between`/`before`/`after`.
2. **La evidencia persistida es suficiente para el match, no para el razonamiento
   completo.** `fact_quarantine` guarda campo, operador, esperado, observado,
   regla, versión, lote y registro; el `trace` detallado del evaluador queda
   en memoria y no se incorpora al finding.
3. **La cobertura explícita todavía es mínima.** Falta probar de forma aislada
   cada operador nuevo, comparaciones field-to-field, valores ausentes,
   tipos/fechas, fuentes explícitas y trazas de árboles anidados.
4. **La presentación compuesta ya existe en el servicio**, pero debe validarse
   con casos de `derived`, `all/any/not` y condiciones malformadas para evitar
   mensajes ambiguos en administración y cuarentena.

### Backlog priorizado para hoy

| Prioridad | Trabajo | Criterio de terminado | Estado |
|---|---|---|---|
| P0 | Cerrar contrato de la DSL explícita | Documentar esquema, operandos válidos, operadores, tipos, missing y semántica inclusiva de fechas; agregar ejemplos JSON versionados | Pendiente |
| P0 | Completar pruebas del evaluador | Cubrir todos los operadores, field-to-field, `all/any/not`, fuentes, valores faltantes, errores de validación y trazas | Pendiente |
| P0 | Verificar findings de reglas compuestas | Confirmar que campo, esperado, observado, fuente, lote, registro y versión quedan correctos para `left/right` y condiciones anidadas | Pendiente |
| P1 | Diseñar la extensión del wizard | Definir una UI accesible para uno o varios predicados, operandos y grupos, con preview humano y fallback POST/HTMX | Pendiente |
| P1 | Implementar la creación gobernada desde UI | Conectar el wizard a `create_complex_rule`, conservar `DRAFT`, scope por reporte, CSRF, autorización y auditoría | Pendiente |
| P1 | Decidir y, si se aprueba, persistir trace | Acordar tamaño, privacidad y formato de evidencia; guardar solo el detalle necesario para reproducir la decisión | Decisión pendiente |
| P2 | Prueba end-to-end de ingesta | Validar `BEFORE` y `AFTER` con una regla compuesta, sin bloquear ni modificar hechos canónicos, y revisar Quarantine | Pendiente |
| P2 | Actualizar mensajes y catálogo operativo | Mostrar condiciones compuestas de forma legible y añadir recetas reproducibles para pruebas manuales | Pendiente |

### Fuera de alcance de hoy

- No convertir findings en bloqueos de importación.
- No modificar, corregir, aprobar o publicar datos de empleados en fuentes
  autoritativas.
- No reemplazar el contrato legado mientras existan reglas ya persistidas.
- No eliminar ni reescribir `rule_findings`, `fact_quarantine` ni evidencia de
  lotes anteriores.

## Editor generico de reglas compuestas

El wizard de reglas ya permite crear condiciones sin depender de una plantilla
de negocio concreta. La condicion se guarda en el mismo contrato versionado
del motor y la regla queda en `DRAFT` hasta que una persona la revise y active.

### Paso a paso para crear una regla de 30 dias de rehire

1. Abrir **Admin > Business rules** y seleccionar **Create rule**.
2. Elegir la fase `AFTER` y como reporte objetivo `ROSTER_LOCK`. Ese scope hace
   que el finding quede asociado al registro de onboarding que se esta
   revisando.
3. En **Condition style**, seleccionar **Multiple comparisons / calculated
   value**.
4. Mantener el grupo `All conditions must match`.
5. En la primera comparacion seleccionar como lado izquierdo el campo
   `ACCESSNOW.accessnow_status`, operador `in` y como valor fijo
   `TERMINATED, DEACTIVATED`.
6. Agregar una segunda comparacion. Seleccionar como lado izquierdo
   **Calculated value > Business days between**.
7. Configurar sus dos entradas como campos: primero
   `ACCESSNOW.termination_date` y segundo `ROSTER_LOCK.onboarding_date`.
8. Seleccionar operador `between` y valor fijo `0, 30`.
9. Continuar con el nombre descriptivo, severidad y revision. Usar **Test**
   sobre la regla `DRAFT` antes de activarla y revisar los resultados en
   **Quarantine**.

El mismo flujo sirve para reglas similares: se pueden cambiar las fuentes,
campos, operador, grupo `all/any`, valores fijos o calculados. El editor no
conoce ni necesita conocer el concepto de rehire.

### Regla de prueba con doble condicion

Usar esta receta para validar el recorrido completo del wizard sin depender de
una logica especial de rehire:

| Campo | Valor |
|---|---|
| Nombre sugerido | `TEST - Terminated record has termination date` |
| Phase | `AFTER` |
| Fuente objetivo | `MASTER_ROSTER` |
| Grupo | `All conditions must match` |
| Severidad | `WARNING` |
| Estado inicial | `DRAFT` |

Configurar las dos comparaciones siguientes:

1. Lado izquierdo **Report field**: `MASTER_ROSTER.assignment_status`;
   operador `equals`; lado derecho **Fixed value**: `TERMINATED`.
2. Lado izquierdo **Report field**: `MASTER_ROSTER.actual_termination_date`;
   operador `exists`; dejar el valor derecho vacio.

La regla debe coincidir solamente cuando ambas condiciones sean verdaderas:
el registro esta terminado y tiene fecha de terminacion. Si una de las dos
condiciones falla, no debe generarse finding. Guardarla como `DRAFT`, usar
**Test**, revisar el conteo y los registros coincidentes, y activarla solo
despues de confirmar el resultado en **Quarantine**. Para probar la variante
OR, cambiar el grupo a `Any condition may match` y verificar que el conteo
aumente de acuerdo con cada condicion individual.

El contrato equivalente queda expresado así:

```json
{
  "all": [
    {
      "left": {"kind": "field", "source": "MASTER_ROSTER", "field": "assignment_status"},
      "operator": "equals",
      "right": {"kind": "literal", "value": "TERMINATED"}
    },
    {
      "left": {"kind": "field", "source": "MASTER_ROSTER", "field": "actual_termination_date"},
      "operator": "exists",
      "right": {"kind": "literal", "value": ""}
    }
  ]
}
```

### Requisito para comparar fuentes

En evaluacion `AFTER`, el motor arma el contexto `sources` con el registro mas
reciente de cada fuente vinculada al mismo `matched_worker_id`. Por eso una
condicion entre fuentes solo puede producir un resultado reproducible cuando
la reconciliacion local ya enlazo los registros. Si no existe ese enlace, el
motor conserva el comportamiento de payload plano y la condicion no debe
interpretarse como una coincidencia.

### Pendiente despues de esta entrega

- Agregar una prueba de integracion con dos registros enlazados de fuentes
  distintas y verificar el finding en el registro ancla.
- Mejorar la proyeccion de `fact_quarantine` para mostrar todos los operandos
  y el trace de una condicion compuesta, en lugar del primer campo solamente.
- Decidir si las reglas `BEFORE` entre fuentes deben esperar un contexto
  previo de reconciliacion o limitarse a una sola fuente.

## Receta de prueba con Roster Lock y Master Roster

La base local revisada el 2026-09-10 contiene evidencia suficiente para probar
una comparacion entre fuentes sin inventar valores:

- `ROSTER_LOCK`: 359 hechos.
- `MASTER_ROSTER`: 3,351 hechos.
- 173 trabajadores tienen registros enlazados en ambas fuentes.
- 543 filas historicas enlazadas cumplen `ROSTER_LOCK.assignment_status = New
  Hire` y tienen el mismo email en ambas fuentes.

Crear esta regla desde el wizard:

| Campo | Configuracion |
|---|---|
| Nombre sugerido | `TEST - Roster Lock hire matches Master Roster email` |
| Phase | `AFTER` |
| Fuente objetivo | `ROSTER_LOCK` |
| Grupo | `All conditions must match` |
| Severidad | `WARNING` |

Comparacion 1:

- Lado izquierdo: campo `ROSTER_LOCK.assignment_status`.
- Operador: `equals`.
- Lado derecho: valor fijo `New Hire`.

Comparacion 2:

- Lado izquierdo: campo `ROSTER_LOCK.email`.
- Operador: `equals`.
- Lado derecho: campo `MASTER_ROSTER.email`.

El scope `ROSTER_LOCK` hace que el finding quede anclado al registro de
Roster Lock. La comparacion de fuentes usa el contexto de registros enlazados
por `matched_worker_id`; no se debe interpretar como coincidencia si el
registro aun no esta enlazado. La vista **Test** debe mostrar coincidencias
historicas, pero la regla no crea findings mientras permanezca en `DRAFT`.

El JSON equivalente es:

```json
{
  "all": [
    {
      "left": {"kind": "field", "source": "ROSTER_LOCK", "field": "assignment_status"},
      "operator": "equals",
      "right": {"kind": "literal", "value": "New Hire"}
    },
    {
      "left": {"kind": "field", "source": "ROSTER_LOCK", "field": "email"},
      "operator": "equals",
      "right": {"kind": "field", "source": "MASTER_ROSTER", "field": "email"}
    }
  ]
}
```

## Configuracion y prueba del 30-day rehire

La regla de rehire debe crearse como una regla generica de tres comparaciones;
no existe una plantilla especial en el motor. Antes de probarla, ingerir en
este orden:

1. `MASTER_ROSTER`, para que exista el trabajador local.
2. Los archivos de `ACCESSNOW`, incluyendo los estados terminados o
   desactivados y su fecha de terminacion.
3. `ROSTER_LOCK`, con el nuevo onboarding y su fecha propuesta.

En el wizard configurar:

| Campo | Configuracion |
|---|---|
| Nombre sugerido | `TEST - 30 business day rehire hold` |
| Phase | `AFTER` |
| Fuente objetivo | `ROSTER_LOCK` |
| Grupo | `All conditions must match` |
| Severidad | `CRITICAL` o `ERROR`, segun la politica de revision |

Comparacion 1:

- Lado izquierdo: `ACCESSNOW.accessnow_status`.
- Operador: `in`.
- Valor fijo: `TERMINATED, DEACTIVATED`.

Comparacion 2:

- Lado izquierdo: **Calculated value > Business days between**.
- Primera entrada: `ACCESSNOW.termination_date`.
- Segunda entrada: `ROSTER_LOCK.onboarding_date`.
- Operador: `between`.
- Valor fijo: `0, 30`.

Comparacion 3, recomendada para evitar fechas vacias:

- Lado izquierdo: `ROSTER_LOCK.onboarding_date`.
- Operador: `exists`.
- Lado derecho: valor fijo vacio.

Luego guardar como `DRAFT`, usar **Test**, revisar el numero de matches y
confirmar que el registro encontrado sea el onboarding de Roster Lock. Solo
despues activar la regla. La activacion revisa tambien batches historicos y
las ingestas posteriores volveran a ejecutar la regla despues de cada batch.

La base local revisada actualmente no tiene hechos de `ACCESSNOW`, por lo que
esta regla no puede generar una coincidencia de rehire hasta que se ingieran
esos archivos y los registros queden enlazados por `matched_worker_id`.
