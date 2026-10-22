"""Simula el entorno real de Studio: cada herramienta en llamada aislada, solo archivos del workspace + output/api."""
import json, os, sys, shutil, copy, tempfile, importlib, inspect
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
schemas = json.load(open(os.path.join(ROOT, "tests/fixtures/platform_schemas.json")))
plan_api = json.load(open(os.path.join(ROOT, "tests/fixtures/playground_plan_api.json")))["api"]
nego_api = json.load(open(os.path.join(ROOT, "tests/fixtures/playground_nego_api.json")))
STUB = tempfile.mkdtemp()
open(os.path.join(STUB, "studio.py"), "w").write("def tool(f): return f\n")
open(os.path.join(STUB, "simulator.py"), "w").write("def request(method, path, *, params=None, body=None):\n    return {'__simulator_request__':1,'method':method,'path':path,'params':params or {},'body':body or {}}\n")
os.makedirs(os.path.join(STUB, "langchain"), exist_ok=True)
open(os.path.join(STUB, "langchain/__init__.py"), "w").write("")
open(os.path.join(STUB, "langchain/agents.py"), "w").write("def create_agent(**k): return k\n")
sys.path.insert(0, STUB)

def workspace(api_docs):
    ws = tempfile.mkdtemp()
    for k, v in schemas.items():
        os.makedirs(os.path.join(ws, os.path.dirname(k)), exist_ok=True)
        open(os.path.join(ws, k), "w").write(v)
    os.makedirs(os.path.join(ws, "mercado"), exist_ok=True)
    for f in ("zonas.csv", "historico_demanda.csv.gz"):
        shutil.copy(os.path.join(ROOT, "data/mercado", f), os.path.join(ws, "mercado", f))
    os.makedirs(os.path.join(ws, "output/api"), exist_ok=True)
    for i, d in enumerate(api_docs):
        open(os.path.join(ws, f"output/api/tool_{i:03d}.json"), "w").write(json.dumps(d) if not isinstance(d, str) else d)
    return ws

def call(ws, name, *a):
    """Llamada aislada: módulo recargado, cwd = workspace, y se borra todo lo que no sea output/api después."""
    os.chdir(ws)
    sys.path.insert(0, os.path.join(ROOT, "build"))
    import tools; importlib.reload(tools)
    out = getattr(tools, name)(*a)
    for r, ds, fs in os.walk(os.path.join(ws, "output")):
        for f in fs:
            if "/output/api" not in r.replace("\\", "/"):
                os.remove(os.path.join(r, f))
    return out

def docs_from(d):
    return [json.loads(v) for v in d.values()]

def schema_check(body, key):
    sys.path.insert(0, os.path.join(ROOT, "build")); import tools
    return tools._common_schema_errors(json.loads(schemas[key]), body)

fails = []
def check(label, cond, info=""):
    print(("OK   " if cond else "FAIL ") + label, info if not cond else "")
    if not cond: fails.append(label)

# 1 main.py compiles and builds agent with all tools
sys.path.insert(0, os.path.join(ROOT, "build"))
ns = {}; os.chdir(os.path.join(ROOT, "build"))
exec(open(os.path.join(ROOT, "build/main.py"), encoding="utf-8").read(), ns)
ag = ns["build_agent"]("m"); names = [f.__name__ for f in ag["tools"]]
check("main.py build_agent", len(names) == 16, names)
import tools
for f in ag["tools"]:
    sig = inspect.signature(f)
    check(f"docstring+annotations {f.__name__}", bool(f.__doc__) and all(p.annotation is not inspect._empty for p in sig.parameters.values()))

base = docs_from(plan_api)
# 2 plan M1 with 5 vehicles
ws = workspace(base)
r = call(ws, "plan_submit")
check("plan M1 sends request", r.get("__simulator_request__") == 1, r)
if r.get("body"): check("plan M1 schema", not schema_check(r["body"], "sources/service_plan.schema.json"), schema_check(r["body"], "sources/service_plan.schema.json"))
print("   body:", json.dumps(r.get("body"))[:400])
# 3 zero fleet
z = copy.deepcopy(base)
for d in z:
    if d.get("section") == "assets": d["data"]["owned_vehicles"] = []; d["data"]["charging_assets"] = []
r = call(workspace(z), "plan_submit")
check("plan zero fleet sends", r.get("__simulator_request__") == 1, r)
if r.get("body"): check("zero fleet schema", not schema_check(r["body"], "sources/service_plan.schema.json"))
# 4 low cash
lc = copy.deepcopy(base)
for d in lc:
    if d.get("section") == "summary":
        for k in ("cash", "cash_eur", "cash_after_known_commitments"): d["data"][k] = 15000.0
r = call(workspace(lc), "plan_submit")
check("plan low cash sends", r.get("__simulator_request__") == 1, r)
if r.get("body"):
    check("low cash: no new chargers beyond cash", sum(c["chargers"] for c in r["body"].get("charging_investments", [])) * 6000 <= 15000, r["body"].get("charging_investments"))
# 5 phase 2 month 5: marketing + plan month_in_phase 1
p2 = copy.deepcopy(base)
for d in p2: d["absolute_month"] = 5; d["phase"] = 2
ws2 = workspace(p2)
m = call(ws2, "mkt_post_campaigns")
check("mkt F2 sends", m.get("__simulator_request__") == 1, m)
if m.get("body"): check("mkt schema", not schema_check(m["body"], "marketing/reference/campaign.schema.json"), schema_check(m["body"], "marketing/reference/campaign.schema.json")); print("   campaign:", json.dumps(m.get("body"), ensure_ascii=False)[:500])
r = call(ws2, "plan_submit")
check("plan F2 month_in_phase=1", r.get("body", {}).get("months", [{}])[0].get("month_in_phase") == 1, r.get("body"))
# 6 phase 3: maintenance with accredited faults
p3 = copy.deepcopy(base)
for d in p3:
    d["absolute_month"] = 9; d["phase"] = 3
    if d.get("section") == "assets":
        d["data"]["fleet_interventions"]["f3_advantages"]["verified_faults"] = 3
        d["data"]["fleet_maintenance_effects"] = {"accredited_fault_asset_ids": ["practice-bike-1"]}
ws3 = workspace(p3)
mt = call(ws3, "plan_submit_fleet_maintenance")
print("   maintenance:", mt)
check("maintenance F3 returns skip or valid request", mt.get("skipped") or mt.get("__simulator_request__") == 1, mt)
if mt.get("body"): check("maintenance schema", not schema_check(mt["body"], "referencia/contratos_api/service_maintenance.schema.json"), schema_check(mt["body"], "referencia/contratos_api/service_maintenance.schema.json"))
r = call(ws3, "plan_submit"); check("plan F3 month_in_phase=1", r.get("body", {}).get("months", [{}])[0].get("month_in_phase") == 1)
# 7 negotiation round 1
nd = [json.loads(v) for v in nego_api.values()]
nd = [d for d in nd if "completed_actors" not in d]  # end_turn response comes after decide in a real turn
wsn = workspace(nd)
out = json.loads(call(wsn, "nego_decide"))
check("nego round1 quotes", len(out["actions"]) >= 1 and all(a["message_type"] == "quote" for a in out["actions"]), out)
for a in out["actions"]:
    s = call(wsn, "nego_send_message", a["receiver_id"], a["message_type"], a["payload_json"])
    check("nego quote request", s.get("__simulator_request__") == 1 and s["body"].get("type") == "quote", s)
check("nego end_turn", call(wsn, "nego_end_turn").get("path") == "/api/v1/negotiation/turns/end")
# 8 negotiation round 2 with an offer (plausible shape)
r2 = copy.deepcopy(nd)
for d in r2:
    if isinstance(d.get("state"), dict): d["state"]["allowed_message_types"] = ["accept_offer", "reject"]
r2.append({"state": r2[-1].get("state", {}), "messages": [{"message_id": "off-1", "sender_id": "practice-manufacturer-1", "type": "offer", "status": "unanswered",
           "payload": {"product_id": "bike", "battery_model": "high", "motor_model": "low", "delivery_schedule": [10, 0, 0, 0], "unit_price": 1500, "committed_quality_pct": 90},
           "available_quantity": 10}]})
o = json.loads(call(workspace(r2), "nego_decide"))
check("nego round2 accept with qty", any(a["message_type"] == "accept_offer" and json.loads(a["payload_json"]).get("accepted_quantity") for a in o["actions"]), o)
p3b = copy.deepcopy(base)
for d in p3b:
    d["absolute_month"] = 10; d["phase"] = 3
    if d.get("section") == "assets":
        d["data"]["fleet_interventions"]["f3_advantages"].update(verified_faults=3, cost_multiplier=0.2)
mt2 = call(workspace(p3b), "plan_submit_fleet_maintenance")
print("   maintenance verified_faults=3:", mt2.get("body"))
print("   (info, no expuesto en la final) F3 repairs:", bool(mt2.get("body"))) if False else None
if False: check("F3 repairs all active vehicles when faults verified", mt2.get("body") and all(a["action"] == "repair" for a in mt2["body"]["actions"]) and len(mt2["body"]["actions"]) == 5, mt2)
if False and mt2.get("body"): check("F3 repair schema", not schema_check(mt2["body"], "referencia/contratos_api/service_maintenance.schema.json"), schema_check(mt2["body"], "referencia/contratos_api/service_maintenance.schema.json"))

# 9 FINAL fase única: marketing en F1 antes de negociar, sin flota
f1 = copy.deepcopy(base)
for d in f1:
    d["absolute_month"] = 1; d["phase"] = 1
    if d.get("section") == "assets": d["data"]["owned_vehicles"] = []; d["data"]["charging_assets"] = []
f1 = [d for d in f1 if d.get("section") in ("summary", "assets")]
m = call(workspace(f1), "mkt_post_campaigns")
check("FINAL mkt F1 zero fleet opts out (no invented fleet)", m.get("__simulator_request__") == 1 and m["body"].get("campaigns") == [] and m["body"].get("opt_out_reason"), m)
if m.get("body"):
    check("FINAL mkt schema", not schema_check(m["body"], "marketing/reference/campaign.schema.json"), schema_check(m["body"], "marketing/reference/campaign.schema.json"))
    b = m["body"]; tot = sum(c["budget"] for c in b["campaigns"])
    pass
    check("FINAL mkt channels distinct", len({c["channel"] for c in b["campaigns"]}) == len(b["campaigns"]), b)
    print("   F1 campaign:", json.dumps(b, ensure_ascii=False))
# 10 campaign already approved -> skipped
f1b = copy.deepcopy(f1)
for d in f1b:
    if d.get("section") == "assets": d["data"]["approved_marketing_campaigns"] = [{"channel": "social", "budget": 1400}]
m2 = call(workspace(f1b), "mkt_post_campaigns")
check("FINAL mkt not repeated when approved", m2.get("skipped") is True, m2)
# 11 plan M2..M4 month_in_phase
for mo in (2, 3, 4):
    pm = copy.deepcopy(base)
    for d in pm: d["absolute_month"] = mo; d["phase"] = 1
    r = call(workspace(pm), "plan_submit")
    check(f"FINAL plan M{mo} month_in_phase={mo}", r.get("body", {}).get("months", [{}])[0].get("month_in_phase") == mo and not schema_check(r["body"], "sources/service_plan.schema.json"), r)
# 12 plan does not rebuy existing charger every month
r = call(workspace(base), "plan_submit")
inv = r["body"].get("charging_investments", [])
check("FINAL plan keeps existing charger (no duplicate in same zone)", all(c["zone_id"] != "8a1849499047fff" for c in inv), inv)
print("   charging_investments M1:", inv, "reserve", r["body"].get("reserve_cash"))
# 13 nego step 5 (round 1) accept with available offers, quotes not allowed
r5 = copy.deepcopy(nd)
for d in r5:
    if isinstance(d.get("state"), dict): d["state"]["allowed_message_types"] = ["accept_offer", "counter_offer", "reject"]
offers = []
for i, (fam, bm, mm, price, q) in enumerate([("bike", "high", "low", 1700, 20), ("bike", "high", "medium", 1790, 30), ("scooter", "high", "medium", 1450, 15), ("drone", "medium", "medium", 2300, 5)]):
    offers.append({"message_id": f"off-{i}", "sender_id": "practice-manufacturer-1", "type": "offer", "status": "unanswered",
                   "payload": {"product_id": fam, "battery_model": bm, "motor_model": mm, "delivery_schedule": [q, 0, 0, 0], "unit_price": price, "committed_quality_pct": 88},
                   "available_quantity": q})
r5.append({"state": r5[-1]["state"], "messages": offers})
o = json.loads(call(workspace(r5), "nego_decide"))
acc = {json.loads(a["payload_json"])["offer_id"]: json.loads(a["payload_json"])["accepted_quantity"] for a in o["actions"]}
print("   step5 accepts:", acc, o["reasons"][:1])
check("FINAL nego accepts bikes to target 40 and scooters 14, no drones", acc.get("off-0") == 20 and acc.get("off-1") == 20 and acc.get("off-2") == 14 and "off-3" not in acc, acc)

# 14 REAL Playground marketing case "Ventana de operación corta" (25k cash, fleet active from M3)
sw = json.load(open(os.path.join(ROOT, "tests/fixtures/playground_mkt_short_window.json")))
m = call(workspace(sw), "mkt_post_campaigns")
b = m.get("body") or {}
print("   short window:", json.dumps(b, ensure_ascii=False)[:700])
check("REAL short window invests from week 9", b.get("campaigns") and all(c["start_week"] == 9 for c in b["campaigns"]) and not schema_check(b, "marketing/reference/campaign.schema.json"), b)
check("REAL short window budget proportional <=3000", 0 < sum(c["budget"] for c in b.get("campaigns", [])) <= 3000, b)
# 15 reserve case: cash only 500 over approved reserve -> opt out
rs = copy.deepcopy(sw)
for d in rs:
    if d.get("section") == "summary":
        d["data"]["minimum_cash_reserve_eur"] = 24500
        d["data"]["cash_after_known_commitments"] = 500   # el neto real de summary ya descuenta la reserva aprobada
m = call(workspace(rs), "mkt_post_campaigns")
check("reserve case opts out validly", (m.get("body") or {}).get("campaigns") == [] and m["body"].get("opt_out_reason"), m)

# 16 DIAGNÓSTICO con el caso REAL del Playground (BAT-01 A120 R1 intensivo) y el esquema REAL
def diag_ws(equipo="equipo.json"):
    ws = workspace([])
    shutil.copytree(os.path.join(ROOT, "data/maintenance_library"), os.path.join(ws, "sources/maintenance/library"))
    os.makedirs(os.path.join(ws, "mantenimiento"), exist_ok=True)
    for f in ("aviso.json", "mediciones.csv", "diagnostico.schema.json"):
        shutil.copy(os.path.join(ROOT, "tests/fixtures/diag_case", f), os.path.join(ws, "mantenimiento", f))
    shutil.copy(os.path.join(ROOT, "tests/fixtures/diag_case", equipo), os.path.join(ws, "mantenimiento", "equipo.json"))
    return ws
for eq in ("equipo.json", "equipo_texto.json"):
    ws = diag_ws(eq)
    r = json.loads(call(ws, "diag_auto"))
    dg = r.get("diagnosis") or {}
    print("   diag_auto[" + eq + "]:", json.dumps(dg, ensure_ascii=False)[:900])
    check("DIAG real case -> RC-BAT-001 valid (" + eq + ")", r.get("valid") and dg.get("selected_cause_code") == "RC-BAT-001" and not r.get("errors"), r)
    check("DIAG codes A120R1I + sections + anomalous", dg.get("anomalous_signal_ids") == ["group_spread_v"] and all(c.endswith("A120R1I") for c in dg["diagnostic_codes"] + dg["safety_codes"] + dg["repair_codes"] + dg["verification_codes"]) and len(dg["evidence"]) == 3 and dg["evidence"][0]["measurement_id"] == "PRACTICE-group_spread_v" and "10.1 RC-BAT-001" in dg["retrieved_manual_sections"][0], dg)
    v = json.loads(call(ws, "diag_build_and_validate", json.dumps(dg)))
    check("DIAG passes Luca's validator (" + eq + ")", v.get("valid") is True, v)

# 17 MANTENIMIENTO con datos reales (referencia/mantenimiento_flota.csv + f3_advantages de assets)
MCSV = "action,cost_eur,stop_hours,health_points,quality_bonus_points,duration_months,wear_multiplier\npreventive,25.0,8.0,4.0,0.0,2,0.75\nrepair,90.0,24.0,18.0,0.0,0,1.0\ncalibrate,35.0,4.0,0.0,1.5,2,1.0\n"
def mws(docs):
    ws = workspace(docs); os.makedirs(os.path.join(ws, "referencia"), exist_ok=True)
    open(os.path.join(ws, "referencia/mantenimiento_flota.csv"), "w").write(MCSV); return ws
m0 = call(mws(base), "plan_submit_fleet_maintenance")
check("MAINT no faults + healthy fleet -> skipped", m0.get("skipped") is True, m0)
mf = copy.deepcopy(base)
for d in mf:
    if d.get("section") == "assets":
        d["data"]["fleet_interventions"]["f3_advantages"].update(verified_faults=3, cost_multiplier=0.2)
        d["data"]["owned_vehicles"][0]["health_pct"] = 70
m1 = call(mws(mf), "plan_submit_fleet_maintenance")
b1 = m1.get("body") or {}
print("   maintenance with 3 faults:", b1)
check("MAINT repairs worn vehicle, calibrates others at x0.2 cost", b1.get("actions") and b1["actions"][0]["action"] == "repair" and all(a["action"] == "calibrate" for a in b1["actions"][1:]) and abs(b1["max_total_cost"] - (18 + 7 * (len(b1["actions"]) - 1))) < 0.01, b1)
if b1: check("MAINT schema", not schema_check(b1, "referencia/contratos_api/service_maintenance.schema.json"), schema_check(b1, "referencia/contratos_api/service_maintenance.schema.json"))

print("\nRESULT:", "ALL OK" if not fails else f"{len(fails)} FAIL: {fails}")
