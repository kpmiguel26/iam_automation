Asunto: IAM Automation Phase 1 - Resumen UAT y decisiones requeridas

Estimados stakeholders,

Comparto adjunto el resumen ejecutivo de UAT para IAM Automation Phase 1.

La definición actual de Phase 1 es una plataforma de reconciliación y auditoría de identidades en modo read-only. El sistema recopila y compara evidencia de las fuentes, presenta hallazgos y facilita la revisión humana. No ejecuta contrataciones, terminaciones, cambios de acceso, provisioning ni modificaciones en los sistemas autoritativos.

El paquete UAT identifica 34 reglas core de Phase 1 y 8 capacidades de plataforma. También separa 5 capacidades de escritor para Phase 2, 4 integraciones futuras y 1 elemento fuera de alcance. De los 36 escenarios revisados, 9 están listos para UAT; los demás requieren decisiones de negocio, controles técnicos o pertenecen a fases posteriores.

Los principales temas para validar son:

- Identificadores que prueban que dos observaciones corresponden a la misma persona.
- Cobertura esperada de cada fuente y ventanas legítimas de latencia.
- Tratamiento de conflictos, diferencias esperadas y evidencia insuficiente.
- Regla exacta para detectar una posible condición de rehire de 30 días.
- Severidad de hallazgos y evidencia requerida para cerrar una revisión.
- Owners responsables de reglas, mappings, calendarios, fuentes y UAT.
- Confirmación técnica del límite read-only.

Agradezco revisar el documento antes de la próxima reunión para que podamos cerrar estas decisiones y continuar con la ejecución UAT enfocada en reconciliación, evidencia y visibilidad operativa.

Saludos,

Miguel Fernandez
WFM Operations | Fullstack Developer
IAM Automation Phase 1
