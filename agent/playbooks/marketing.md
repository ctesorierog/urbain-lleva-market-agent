## TAREA: MARKETING
Solo fase 2 (M5–M8). La campaña se publica UNA vez por cuatrimestre y SIEMPRE antes del plan mensual.
Orden fijo: get_company_state("summary") y get_company_state("assets") → plan_prepare_context() → si campaign_posted es true, termina sin publicar → mkt_post_campaigns() sin argumentos (calcula y publica en la misma llamada).
mkt_build_campaign decide de forma determinista: presupuesto ≤3.000 € (y ≤ marketing_budget_limit_eur, sin bajar de CASH_FLOOR_EUR), canales leídos de marketing/reference/, público young (casas en Gros, campus en Antiguo/Ibaeta) y adults para cenas, mensajes concretos y creíbles con precio y llamada a la acción.
Si no hay flota activa ni entregas pendientes, o la flota está saturada (>25 % de demanda perdida por vehículo o recarga), devuelve una renuncia válida: campaigns=[] con opt_out_reason. Publícala igualmente con mkt_post_campaigns para dejarla registrada.
No reescribas los mensajes: evita promesas absolutas ("nunca", "siempre", "garantizado"), restan credibilidad y se cobran igual.
Si el TASK_REQUEST de marketing llega fuera de fase 2, no publiques nada y explícalo.
