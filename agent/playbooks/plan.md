## TAREA: PLAN MENSUAL
Orden fijo (máx. 8 llamadas). Los archivos que escribe una herramienta NO llegan a la siguiente: cada herramienta plan_* recalcula sola a partir de las respuestas de get_company_state. No pases rutas ni JSON entre herramientas.
1. get_company_state("summary"), get_company_state("assets") y get_company_state("results").
2. plan_prepare_context() (opcional, para ver el contexto y explicarlo en el resumen).
3. Solo en fase 3: plan_submit_fleet_maintenance() sin argumentos (repara fallos acreditados) ANTES del plan.
4. Solo en fase 2 y si no hay campaña publicada: mkt_post_campaigns() sin argumentos ANTES del plan. Si se rechaza por campaña existente, continúa.
5. plan_submit() SIN argumentos: calcula, valida y entrega el plan del mes en una sola llamada. Es la entrega oficial: llámala una vez.
6. Resume en 3–5 líneas el recibo (aceptado/rechazado), flota activa, cargadores y prioridades. Si plan_submit devuelve error, explícalo y no lo repitas.
Las herramientas ya aplican: tarifas en límites para exactamente los 2 servicios, solo flota recibida y activa, cada zona con flota tiene cargador, Altza y Aiete con al menos un vehículo, caja ≥ CASH_FLOOR_EUR, claves según el esquema real. Sin flota activa se envía igualmente un plan válido.
