## TAREA: NEGOCIACIÓN
Orden fijo (máx. 14 llamadas). No hay invoke.json: la fase y la ronda vienen en TASK_REQUEST.
1. get_company_state("summary") y get_company_state("commitments") (caja, pagos pendientes, contratos).
2. get_company_state("assets") (flota ya recibida).
3. nego_list_actors() y nego_get_messages() (permisos del turno, catálogo, ofertas recibidas).
4. nego_decide(): calcula las acciones de forma determinista (bicicletas y patinetes primero; drones solo como reserva pequeña para comida; misma necesidad a todos los fabricantes compatibles para que compitan; en accept_offer ya incluye accepted_quantity; respeta caja, CASH_FLOOR_EUR y el límite de gasto de fase).
5. Envía CADA acción devuelta, tal cual, con nego_send_message(receiver_id, message_type, payload_json). No cambies cantidades, precios ni IDs. Si una devuelve error, no la repitas a ciegas: continúa con la siguiente.
6. Termina SIEMPRE con nego_end_turn(), también si nego_decide no devuelve acciones. Después de pedir presupuestos, no esperes respuestas en bucle.
7. Resume en 3–5 líneas: presupuestos pedidos, aceptaciones (pendientes de cierre global, aún no son flota) y necesidad sin cubrir.
Reglas: ronda 1 (service_outbound) solo permite quote; con ofertas vigentes, accept_offer. Ignora ofertas ya respondidas o sustituidas. Un contrato no es flota recibida.
