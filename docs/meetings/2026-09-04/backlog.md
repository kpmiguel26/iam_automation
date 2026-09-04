# Backlog para Programar
## Epic 1: Business Rules Administration


## Story BR-001
Create Business Rules Management Page

Acceptance Criteria:
    Crear regla.
    Editar regla.
    Desactivar regla.
    Ver listado de reglas.


## Story BR-002
Support Thirty-Day Rehire Rule

Acceptance Criteria: 
    Configuración de días.
    Configuración de excepción.
    Validación en import.

## Story BR-003
Support No-Rehire Rule

Acceptance Criteria:
    Configuración por administrador.
    Evaluación automática.


Story BR-004

Field Protection Configuration

Acceptance Criteria

Selección de campos protegidos.
Restricción durante import.


Story BR-005

Import Validation Engine

Acceptance Criteria

Evaluar reglas durante importación.
Generar resultados.
Registrar auditoría.
Story BR-006

Search Validation Engine

Acceptance Criteria

Evaluar restricciones durante búsquedas.
Mostrar advertencias aplicables.


## Epic 2: Alert Framework
Story AL-001

Create Alert Definition Page

Story AL-002

Support Custom Alert Rules

Story AL-003

Alert Severity Levels
INFO
WARNING
ERROR
CRITICAL

Story AL-004

Alert Dashboard

Visualización de:

Alertas activas.
Alertas disparadas hoy.
Historial.
Epic 3: Database Publishing
Story DB-001

Fix Missing Refresh Notification

Story DB-002

Automatic Refresh Polling

Verificación automática cada X segundos.

Story DB-003

Publish Progress Indicator

Mostrar:
Publishing...
Uploading to OneDrive...
Updating SharePoint...
Completed

Riesgos Identificados
Riesgo 1

Las reglas podrían crecer rápidamente y volverse difíciles de mantener.

Mitigación

Diseñar framework genérico desde el inicio.
Riesgo 2

Dependencia de OneDrive + SharePoint introduce retrasos de 5-10 minutos.

Mitigación

Mejorar visibilidad del estado de sincronización.
Riesgo 3

Las alertas configurables pueden requerir un motor de reglas más complejo.

Mitigación

Implementar inicialmente reglas basadas en condiciones simples.


Próximo Hito
Para el lunes
Revisar escenarios pendientes con Sofía.
Validar diseño funcional del framework.


Para el martes 8
Entregar:
Business Rules Configuration Page.
Business Rules Engine.
Fix de Refresh Alert.
Testing completado. ✅
