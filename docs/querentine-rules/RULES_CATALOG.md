# Quarantine rules catalog

Catálogo de reglas para recrear después de limpiar `runtime.sqlite`.

La interfaz de reglas crea inicialmente las reglas como `DRAFT`. Después de
revisar la condición hay que activarlas desde **Business rules**.

## Importante: alcance por fuente

Las reglas se evalúan después de guardar la ingesta y sus findings aparecen en
**Quarantine**. Las reglas `BEFORE` se evalúan sobre las filas normalizadas
antes de ejecutar el adaptador; las `AFTER` se evalúan después de guardar los
hechos en SQLite.

El wizard permite seleccionar `All reports` o una fuente concreta. Las reglas
marcadas como **Compartida** pueden usar `All reports`; las reglas marcadas como
**Específica** deben seleccionar su reporte para evitar marcar como ausente un
campo que simplemente no pertenece a otra fuente.

## Comportamiento en fase 1

`BEFORE` y `AFTER` no son bloqueantes. Una regla `BEFORE` detecta la coincidencia
antes del adaptador y la enlaza al lote cuando este crea sus registros; una
regla `AFTER` detecta la coincidencia directamente sobre los hechos persistidos.
Una infracción nunca cancela la importación ni deshace los datos recibidos.

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

1. Crear y activar `RL-MR-001 — Employee email is missing`.
2. Crear y activar `RL-MR-002 — Terminated assignment requires review`.
3. En las reglas específicas, seleccionar primero el reporte correspondiente
   (`Roster Lock` o `Master Roster`) para que el wizard limite los fields.
4. Ejecutar o reintentar la evaluación de reglas sobre el batch importado.
5. Revisar los resultados en **Quarantine**, verificando regla, empleado, campo
   afectado y valor observado.

## Registro de recreación

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
