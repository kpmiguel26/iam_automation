# Estimación de trabajo — Action Items IAM

**Responsable de esta estimación:** Miguel Fernandez  
**Fecha:** 25 de agosto de 2026  
**Rama de referencia:** `production`

## Resumen ejecutivo

Para los compromisos que requieren trabajo de Miguel, se recomienda reservar **75 horas base** y una contingencia de **5 horas**, para un total de **80 horas de booking**. Esto equivale aproximadamente a **10 días laborables de 8 horas**, aunque no todo el tiempo puede ejecutarse en paralelo porque depende de decisiones de Salesforce, formatos aprobados y resultados de pruebas del equipo IAM.

La carga principal corresponde a:

| Trabajo | Horas base |
| --- | ---: |
| Configuración final de eventos de auditoría | 8 |
| Visibilidad de solicitudes de cambio de rol | 10 |
| Reporte exportable de registros duplicados | 12 |
| Consolidación/merge de perfiles canónicos duplicados | 28 |
| Pruebas de historial, retención, Salesforce y regresión | 14 |
| SOP y handoff técnico | 3 |
| **Total base** | **75** |
| Contingencia por decisiones, ajustes de datos y UAT | **5** |
| **Total recomendado para booking** | **80** |

## Supuestos de la estimación

- El sistema actual se conserva: SQLite local, flujo de solicitudes aprobado, publicación controlada y auditoría append-only.
- Salesforce continúa siendo un destino de exportación mediante workbook/Data Loader; no se incluye construir una integración API con Salesforce.
- Los formatos finales de Salesforce, reglas de roles, valores de licencia y permisos administrativos deben ser confirmados por Salesforce antes de cerrar la implementación.
- El merge de perfiles no elimina evidencia histórica. Debe conservar snapshots, identificadores, eventos de auditoría y una relación entre el perfil sobreviviente y el perfil fusionado.
- Las horas incluyen análisis técnico, implementación, pruebas automatizadas, pruebas manuales básicas y documentación técnica. No incluyen esperas por aprobaciones externas.
- Las estimaciones tienen una precisión esperada de aproximadamente ±20% hasta que se confirmen los archivos y reglas definitivos.

## Plan de trabajo de Miguel

| Prioridad | Tarea | Módulos/áreas probables | Actividades | Horas | Fecha objetivo |
| ---: | --- | --- | --- | ---: | --- |
| 1 | Configuración final de audit events | `audit.py`, `audit_service.py`, rutas administrativas, pruebas de auditoría | Revisar cobertura de eventos, completar actor/rol/equipo/correlation ID, validar eventos de éxito y error, confirmar retención y evidencia, agregar pruebas y actualizar guía | 8 | 11-sep-2026 |
| 2 | Visibilidad de change-role submissions | `change_request.py`, `request_service.py`, rutas/templates administrativas, `master_audit.html` | Definir estados y filtros, mostrar solicitudes por usuario/empleado/rol/fecha/estado, enlazar decisiones y eventos de auditoría, agregar pruebas de permisos y exportación/consulta | 10 | 4-sep-2026 |
| 3 | Reporte exportable de duplicados | `report_service.py`, `report_routes.py`, `templates/reports/duplicates.html`, pruebas de reportes | Confirmar columnas y reglas de duplicidad, implementar consulta consolidada, agregar CSV/XLSX o formato exportable existente, incluir fecha, fuente, identificadores, estado y recomendación, probar con fixtures | 12 | 4-sep-2026 |
| 4 | Merge de perfiles canónicos duplicados | `worker_history_service.py`, modelo/repositorios SQLite, servicios de empleados, `duplicate_review.html` | Diseñar flujo de revisión/aprobación, validar identidad y conflictos, conservar historial y aliases, registrar merge event, actualizar referencias sin pérdida de auditoría, permitir rollback/recovery y cubrir concurrencia | 28 | 11-sep-2026 |
| 5 | Pruebas de historial y retención | historial de workers, auditoría, snapshots, backups y reglas de retención | Crear matriz de casos, ejecutar pruebas de rehire/merge/retención/archivo, verificar que no se borre evidencia requerida, documentar resultados y defectos | 8 | 11-sep-2026 |
| 6 | Pruebas de Salesforce y Data Loader | `salesforce_export_service.py`, guía Salesforce y fixtures | Ejecutar exportación con el template aprobado, revisar columnas y valores con Salesforce Team, validar descarga y carga controlada, corregir mapping si procede | 6 | 4-sep-2026 |
| 7 | SOP y handoff técnico | `docs/guides/SALESFORCE_EXPORT_CONFIGURATION.md`, documentación operativa | Entregar pasos, precondiciones, responsables, evidencia esperada, recovery y límites de soporte para que Sofia complete el SOP | 3 | 11-sep-2026 |
| 8 | Contingencia e integración | Todo lo anterior | Ajustes derivados de UAT, cambios del template, defectos de datos, revisiones de seguridad y coordinación | 8 | Reserva |

## Desglose de los action items recibidos

| Action item | Owner indicado | Participación de Miguel | Booking recomendado | Dependencia/resultado |
| --- | --- | --- | ---: | --- |
| Completar demostración de Salesforce y confirmar Data Loader | Salesforce Team / IAM Team | Preparar/exportar workbook y apoyar la demostración | 4 h | Salesforce debe confirmar el proceso y el template final |
| Confirmar accesos administrativos de Salesforce | Salesforce Team | Entregar requisitos técnicos del export y permisos necesarios | 1 h | No depende de cambio de código salvo que aparezca un requisito nuevo |
| Confirmar descarga del reporte de inactividad de cinco días | Sofia Moya | Apoyar validación si el reporte alimenta el flujo IAM | 0–1 h | Sofia debe confirmar disponibilidad y formato |
| Completar pruebas de aplicación y Salesforce | IAM Team | Ejecutar pruebas de exportación, regresión y defectos asignados | 14 h | Requiere template y acceso/confirmación de Salesforce |
| Actualizar y completar SOP | Sofia Moya | Proporcionar pasos técnicos, evidencia y recovery | 3 h | Sofia consolida y aprueba el SOP |
| Completar configuración final de audit events | Miguel Fernandez | Responsable directo | 8 h | Reglas finales de auditoría y retención |
| Continuar pruebas históricas y de retención | IAM Team | Diseñar y ejecutar casos relacionados con merge, rehire y archivo | 8 h | Política de retención confirmada |
| Agregar visibilidad a change-role submissions | Miguel Fernandez | Responsable directo | 10 h | Estados, filtros y permisos acordados |
| Crear reporte exportable de duplicados | Miguel Fernandez | Responsable directo | 12 h | Reglas de duplicidad y columnas aprobadas |
| Agregar duplicados de roster lock a la reunión quincenal | Sophie Moya Bermudez | Sin desarrollo directo; entregar evidencia si se solicita | 0 h | Actividad operativa de la reunión |
| Probar consolidación de roster-lock por Report Studio | Amanda Madrigal | Apoyar con datos/defectos si afecta el modelo canónico | 2–4 h de apoyo | Amanda ejecuta la prueba principal |
| Desarrollar merge de perfiles canónicos duplicados | Miguel Fernandez | Responsable directo | 28 h | Reglas de precedencia, aprobación y recuperación |
| Retrasar comunicación/acceso de vendors | IAM Team | No requiere desarrollo | 0 h | Se mantiene como control operativo hasta estabilizar el flujo |

## Booking recomendado por fecha

### Hasta el 4 de septiembre de 2026

Reservar aproximadamente **30 horas** de Miguel para:

- Visibilidad de solicitudes de cambio de rol: 10 h.
- Reporte exportable de duplicados: 12 h.
- Salesforce/Data Loader y pruebas de aplicación: 8 h.

El objetivo es llegar al 4 de septiembre con los flujos demostrables, exportaciones revisadas y defectos críticos identificados.

### Del 5 al 11 de septiembre de 2026

Reservar aproximadamente **42 horas** de Miguel para:

- Configuración final de auditoría: 8 h.
- Merge de perfiles canónicos: 28 h.
- Historial/retención y apoyo al SOP: 6 h.

El objetivo es cerrar evidencia, pruebas de recuperación, documentación y handoff antes del 11 de septiembre.

## Criterios de terminado

- Cada cambio genera eventos de auditoría con actor, acción, entidad, resultado, timestamp y correlation ID.
- Las solicitudes de cambio de rol pueden localizarse y revisarse por estado, usuario, empleado y fecha, respetando autorización.
- El reporte de duplicados se puede descargar y contiene datos suficientes para decidir la resolución.
- El merge exige revisión/aprobación, conserva historial y aliases, registra la relación de merge y no borra evidencia auditada.
- Las pruebas cubren duplicados, conflictos, reintentos, rollback/recovery, rehire y retención.
- El export de Salesforce se valida contra el template aprobado y se documenta el handoff al Data Loader.
- Los defectos abiertos, decisiones pendientes y limitaciones quedan registrados antes del cierre.

## Riesgos que pueden aumentar las horas

- Cambios del template Salesforce después de iniciar el desarrollo.
- Reglas no definidas para elegir el perfil canónico sobreviviente.
- Necesidad de modificar el esquema SQLite o migraciones existentes para soportar merge events.
- Requisitos adicionales de retención, legal hold o exportación de evidencia.
- Pruebas de acceso administrativo que requieran coordinación con Salesforce Team.
- Datos reales con identificadores incompletos o conflictos entre Roster Lock, AccessNow, RSR y Salesforce.

## Recomendación final

Miguel debería reservar **80 horas** para estos action items. Si el calendario solo permite reservar hasta el 11 de septiembre, la prioridad debe ser:

1. Auditoría final y visibilidad de solicitudes.
2. Reporte exportable de duplicados.
3. Pruebas Salesforce/Data Loader.
4. Merge de perfiles canónicos con historial y recuperación.

El merge es el trabajo de mayor riesgo y no debería comprometerse como una simple tarea de reporte: requiere diseño de reglas, cambios de persistencia, pruebas de integridad y revisión de auditoría.

<!-- #endfile -->
