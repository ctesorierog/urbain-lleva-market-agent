# tools_plan.py · OWNER: Carlos · monthly service plan + marketing (see INTERFACE.md)
# MERGE:STRIP
from tools_common import *  # local testing only; merge.py removes this block
# MERGE:END
import json
import math
import re
from pathlib import Path

from studio import tool
from simulator import request

# ---------------------------------------------------------------- policy parameters
# Market areas we serve, matched by keyword against market_area in the zone catalog.
PLAN_AREAS = {"centro": "Centro", "gros": "Gros", "amara": "Amara",
              "antiguo": "Antiguo", "altza": "Altza", "aiete": "Aiete"}
# Blend of analysis/fleet_scenarios.md (demand) and STUDENT_FOCUS.md (Gros homes, Antiguo campus).
PLAN_AREA_WEIGHTS = {"centro": 27.0, "gros": 24.0, "antiguo": 20.0,
                     "amara": 11.0, "altza": 9.0, "aiete": 9.0}
PLAN_EQUITY_AREAS = ("altza", "aiete")              # always at least 1 vehicle + charger
PLAN_AREA_PRIORITY = ["centro", "gros", "antiguo", "altza", "aiete", "amara"]   # small fleets / scarce cash
PLAN_DENSITY_ORDER = ["centro", "gros", "amara", "antiguo", "altza", "aiete"]   # scooters go dense first
PLAN_SCOOTER_CAP_SHARE = 0.7
PLAN_VEHICLES_PER_CHARGER = 20
PLAN_MAX_CELLS_PER_AREA = 2
PLAN_MIN_CELLS = {"amara": 2}                        # Amara is spread out: only 37 % of origins within 1 km of its top cell
PLAN_FARES = {"passenger_transport": {"base_fare": 2.95, "price_per_km": 0.98},
              "food_delivery": {"base_fare": 2.90, "price_per_km": 0.95}}
PLAN_FARE_STEP = 0.05                                # relative move per month when adapting
PLAN_FARE_FLOOR = {"base": 2.60, "km": 0.90}          # do not race to the bottom (financial 33.7 %)
PLAN_MAINT_COST = {"repair": 90, "calibrate": 35}
PLAN_MAINT_BUFFER_EUR = 5000
PLAN_INACTIVE_STATUS = ("pending", "ordered", "transit", "contract", "cancel", "retired",
                        "sold", "scrap", "awaiting", "reserved", "scheduled")
MKT_MAX_BUDGET_EUR = 3000
MKT_MIN_BUDGET_EUR = 600
MKT_SATURATION_LOST_SHARE = 0.25
MKT_FALLBACK_CHANNELS = ["social", "search", "partners"]
MKT_CHANNEL_PREF = {"young": ["social", "redes", "instagram", "tiktok", "univers", "campus", "student", "estudi"],
                    "food": ["search", "busca", "partner", "app", "delivery", "restaur", "socio"]}


# ---------------------------------------------------------------- generic readers
def _plan_load(path):
    p = Path(str(path))
    if not p.is_file() or p.stat().st_size > 30_000_000:
        return None
    try:
        if p.suffix == ".gz":
            return None
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None


def _plan_invoke():
    for p in ("input/invoke.json", "runtime/invoke.json"):
        d = _plan_load(p)
        if isinstance(d, dict):
            return d
    return {}


def _plan_walk(obj, depth=0):
    if depth > 12:
        return
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _plan_walk(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _plan_walk(v, depth + 1)


def _plan_num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and math.isfinite(v):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _plan_first_num(docs, keys):
    for d in docs:
        for node in _plan_walk(d):
            for k in keys:
                n = _plan_num(node.get(k))
                if n is not None:
                    return n
    return None


def _plan_int_in(text, default):
    m = re.search(r"\d+", str(text)) if text is not None else None
    return int(m.group()) if m else default


def _plan_family(node):
    for k in ("product_id", "family", "vehicle_type", "asset_type", "product", "variant_id", "type", "kind"):
        v = node.get(k)
        if isinstance(v, str):
            low = v.lower()
            for fam in ("bike", "scooter", "drone"):
                if low.startswith(fam) or low.split(":")[0] == fam:
                    return fam
    return None


def _plan_is_charger(node):
    if node.get("charging_option_id"):
        return True
    for k in ("asset_type", "type", "kind", "category", "asset_class"):
        v = node.get(k)
        if isinstance(v, str) and ("charg" in v.lower() or "carga" in v.lower()):
            return True
    return False


def _plan_status_inactive(node):
    s = str(node.get("status") or node.get("state") or "").lower()
    return any(w in s for w in PLAN_INACTIVE_STATUS)


def _plan_month_of(node, keys):
    """Mes absoluto (M1–M12) de la primera clave presente; admite "M6" y fase + mes relativo."""
    for k in keys:
        v = node.get(k)
        if v is None or isinstance(v, bool):
            continue
        m = _plan_num(v)
        if m is None:
            m = _plan_int_in(v, None)
        if m is None:
            continue
        ph = node.get("activation_phase") or node.get("phase")
        if ph is not None and m <= 4 and _plan_int_in(ph, 0) > 1:
            m = (_plan_int_in(ph, 1) - 1) * 4 + m
        return m
    return None


def _plan_is_active(node, cur_abs, mip):
    """Activo si activation_month <= mes actual; sin fecha: recibido + 1 mes; sin fechas: activo si
    tiene un status no inactivo (idle, ready, charging...); sin status ni fechas: se asume el mes siguiente."""
    if _plan_status_inactive(node):
        return False
    act = _plan_month_of(node, ("activation_month", "active_from_month"))
    if act is not None:
        return act <= cur_abs
    r = _plan_month_of(node, ("received_month", "delivered_month", "delivery_month", "reception_month"))
    if r is not None:
        return r + 1 <= cur_abs
    return bool(str(node.get("status") or node.get("state") or "").strip())


PLAN_CONTRACT_KEYS = ("contract_id", "offer_id", "quantity", "accepted_quantity", "requested_quantity",
                      "delivery_schedule", "available_quantity", "supplier_id", "seller_id")


def _plan_catalog(inv):
    """zone_id -> (area_key|None, market_area) desde zone_catalog_path (csv o json)."""
    paths = [inv.get("zone_catalog_path"), "mercado/zonas.csv", "data/mercado/zonas.csv"]
    for p in paths:
        if not p or not Path(str(p)).is_file():
            continue
        rows = []
        if str(p).endswith(".csv"):
            import csv
            with open(p, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        else:
            d = _plan_load(p)
            rows = [n for n in _plan_walk(d) if "zone_id" in n]
        cat = {}
        for r in rows:
            zid = r.get("zone_id")
            area = str(r.get("market_area") or r.get("area") or r.get("name") or "")
            if zid:
                cat[str(zid)] = (_plan_area_key(area), area)
        if cat:
            return cat, str(p)
    return {}, None


def _plan_area_key(name):
    low = str(name).lower()
    for k in PLAN_AREAS:
        if k in low:
            return k
    return None


def _plan_cell_scores(inv, catalog):
    """Puntuación por celda H3: orígenes pax+comida + bonus a jóvenes (casas y campus)."""
    import csv
    import gzip
    paths = [inv.get("demand_history_path"), "mercado/historico_demanda.csv.gz",
             "mercado/historico_demanda.csv", "data/mercado/historico_demanda.csv.gz"]
    scores = {}
    for p in paths:
        if not p or not Path(str(p)).is_file():
            continue
        opener = gzip.open if str(p).endswith(".gz") else open
        try:
            with opener(p, "rt", encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    if r.get("service_id") not in APPROVED_SERVICES:
                        continue
                    young = r.get("customer_segment") == "young"
                    o, d = r.get("origin_h3") or r.get("origin_zone"), r.get("destination_h3")
                    if o in catalog:
                        scores[o] = scores.get(o, 0) + (1.5 if young else 1.0)
                    if young and d in catalog:
                        scores[d] = scores.get(d, 0) + 0.5
        except (OSError, EOFError, csv.Error):
            continue
        if scores:
            break
    return scores


def _plan_lost(docs):
    """Agrega demanda perdida por causa (no_vehicle, recharge, competitor, busy...) del último cierre."""
    lost = {}
    for d in docs:
        for node in _plan_walk(d):
            for k, v in node.items():
                lk = k.lower()
                if ("lost" in lk or "unserved" in lk or "perdid" in lk) and isinstance(v, dict):
                    for cause, n in v.items():
                        n = _plan_num(n)
                        if n is not None:
                            c = str(cause).lower()
                            key = ("no_vehicle" if "vehic" in c or "fleet" in c or "capacity" in c else
                                   "recharge" if "charg" in c or "carga" in c or "battery" in c else
                                   "competitor" if "compet" in c or "price" in c else
                                   "busy" if "busy" in c or "ocup" in c or "wait" in c else c)
                            lost[key] = lost.get(key, 0) + n
        if lost:
            break
    return lost


def _plan_kpis(docs):
    k = {}
    for name, keys in {"served": ("served_requests", "served", "completed_requests", "requests_served"),
                       "requests": ("total_requests", "requests", "demand"),
                       "profit_eur": ("profit_eur", "profit", "net_result_eur", "result_eur"),
                       "revenue_eur": ("revenue_eur", "revenue"),
                       "score": ("service_score", "score", "total_score")}.items():
        v = _plan_first_num(docs, keys)
        if v is not None:
            k[name] = round(v, 2)
    return k


def _plan_last_prices(docs):
    for d in docs:
        for node in _plan_walk(d):
            pr = node.get("prices")
            if isinstance(pr, list) and pr and all(isinstance(p, dict) and "service_id" in p for p in pr):
                return {p["service_id"]: {"base_fare": _plan_num(p.get("base_fare")),
                                          "price_per_km": _plan_num(p.get("price_per_km"))} for p in pr}
    return {}


def _plan_campaign_posted(docs):
    for d in docs:
        for node in _plan_walk(d):
            for k in ("marketing_campaigns", "campaigns", "marketing"):
                v = node.get(k)
                if isinstance(v, list) and any(isinstance(c, dict) and c.get("channel") for c in v):
                    return True
                if isinstance(v, dict) and (v.get("campaigns") or v.get("opt_out_reason")):
                    return True
    return False


def _plan_accredited(docs):
    """asset_id de vehículos con fallo acreditado y sin reparación pagada."""
    ids = set()
    for d in docs:
        for node in _plan_walk(d):
            aid = node.get("asset_id") or node.get("vehicle_id")
            if not aid:
                continue
            flat = json.dumps(node, ensure_ascii=False).lower()
            if node.get("repaired") or node.get("repair_paid") or "repair_paid\": true" in flat:
                continue
            accredited = any(node.get(k) is True for k in ("accredited", "acreditado", "is_accredited"))
            st = str(node.get("status") or node.get("evaluation") or node.get("result") or "").lower()
            if accredited or "accredit" in st or "acredit" in st:
                ids.add(str(aid))
    return sorted(ids)


def _plan_f3(docs):
    """Ventajas F3 reales: assets.data.fleet_interventions.f3_advantages y reparaciones guiadas ya hechas."""
    out = {"verified_faults": 0, "cost_multiplier": 1.0, "repaired_asset_ids": []}
    for d in docs:
        data = d.get("data") if isinstance(d, dict) else None
        fi = data.get("fleet_interventions") if isinstance(data, dict) else None
        if isinstance(fi, dict):
            adv = fi.get("f3_advantages") or {}
            out["verified_faults"] = int(_plan_num(adv.get("verified_faults")) or 0)
            out["cost_multiplier"] = _plan_num(adv.get("cost_multiplier")) or 1.0
            out["repaired_asset_ids"] = sorted(str(k) for k in (fi.get("guided_repair_phase") or {}))
    return out


# ---------------------------------------------------------------- context
def _plan_context(response_paths=()):
    inv = _plan_invoke()
    phase = _plan_int_in(inv.get("phase") or (inv.get("calendar") or {}).get("phase"), 1)
    cal = inv.get("calendar") if isinstance(inv.get("calendar"), dict) else {}
    mip = _plan_int_in(inv.get("month_in_phase") or cal.get("month_in_phase"), 1)
    mip = min(max(mip, 1), 4)
    cur_abs = (phase - 1) * 4 + mip
    docs, used = [], []
    for p in [inv.get("state_path"), inv.get("full_state_path"), *response_paths]:
        d = _plan_load(p) if p else None
        if d is not None:
            docs.append(d)
            used.append(str(p))
    for d in _common_api_docs():
        if isinstance(d, dict) and (d.get("source") == "own_company_state" or "section" in d):
            docs.append(d)
            used.append("output/api:" + str(d.get("section")))
    if not inv:
        # Contrato actual: sin invoke.json. Fase y mes absolutos vienen en las respuestas de empresa.
        for d in docs:
            if isinstance(d, dict) and _plan_num(d.get("absolute_month")):
                cur_abs = int(_plan_num(d.get("absolute_month")))
                phase = _plan_int_in(d.get("phase"), (cur_abs - 1) // 4 + 1)
                mip = min(max(cur_abs - (phase - 1) * 4, 1), 4)
                break
    for folder in ("resultados", "empresa"):
        if Path(folder).is_dir():
            for p in sorted(Path(folder).glob("*.json"))[-6:]:
                d = _plan_load(p)
                if d is not None:
                    docs.append(d)
                    used.append(str(p))
    catalog, cat_path = _plan_catalog(inv)
    fleet, chargers, chargers_pending, uncertain, seen, families = {}, {}, {}, 0, set(), set()
    charger_doc = None
    for di, d in enumerate(docs):
        for node in _plan_walk(d):
            if any(k in node for k in PLAN_CONTRACT_KEYS):
                continue  # contrato/oferta/agregado: nunca es flota recibida
            aid = node.get("asset_id") or node.get("vehicle_id") or node.get("charger_id") or node.get("id")
            if _plan_is_charger(node):
                zid = node.get("zone_id")
                individual = "chargers" not in node and (node.get("asset_id") or node.get("charger_id"))
                if not zid or not individual or aid in seen or _plan_status_inactive(node):
                    continue
                if charger_doc is not None and charger_doc != di:
                    continue  # los cargadores se cuentan en un solo documento (evita doble conteo)
                charger_doc = di
                seen.add(aid)
                act = _plan_month_of(node, ("activation_month", "active_from_month"))
                bucket = chargers_pending if act is not None and act > cur_abs else chargers
                bucket[str(zid)] = bucket.get(str(zid), 0) + 1
                continue
            if not aid or aid in seen:
                continue
            fam = _plan_family(node)
            if fam is None:
                continue
            seen.add(aid)
            families.add(fam)
            if _plan_is_active(node, cur_abs, mip):
                fleet.setdefault(fam, []).append(str(aid))
            else:
                uncertain += 1
    # Formato real de assets: data.charging_assets = [{zone_id, chargers, activation_month, ...}]
    real_ch = None
    for d in docs:
        data = d.get("data") if isinstance(d, dict) else None
        if isinstance(data, dict) and isinstance(data.get("charging_assets"), list):
            real_ch = data["charging_assets"]
    if real_ch is not None:
        chargers, chargers_pending = {}, {}
        for c in real_ch:
            zid, n = c.get("zone_id"), int(_plan_num(c.get("chargers")) or 1)
            if not zid:
                continue
            act = _plan_month_of(c, ("activation_month", "active_from_month"))
            bucket = chargers_pending if act is not None and act > cur_abs else chargers
            bucket[str(zid)] = bucket.get(str(zid), 0) + n
    summary_cash = _plan_first_num(docs, ("cash_eur", "available_cash_eur", "cash_balance_eur", "cash", "treasury_eur"))
    pending = _plan_first_num(docs, ("pending_vehicle_payments_eur", "pending_payments_eur", "pending_payment_eur"))
    if pending is None:
        pending = 0.0
        for d in docs:
            for node in _plan_walk(d):
                for k in ("remaining_payment_eur", "balance_due_eur", "amount_due_eur", "pending_amount_eur"):
                    n = _plan_num(node.get(k))
                    if n:
                        pending += n
                        break
            if pending:
                break
    human_reserve = _plan_first_num(docs, ("minimum_reserve_cash_eur", "min_reserve_cash_eur",
                                           "reserve_minimum_eur", "strategic_reserve_eur", "minimum_cash_reserve_eur"))
    mkt_limit = _plan_first_num(docs, ("marketing_budget_limit_eur",))
    mkt_committed = _plan_first_num(docs, ("marketing_committed_eur", "approved_marketing_eur")) or 0.0
    area_zones = {}
    for zid, (ak, _) in catalog.items():
        if ak:
            area_zones.setdefault(ak, []).append(zid)
    ctx = {
        "phase": phase, "month_in_phase": mip, "absolute_month": cur_abs,
        "active_fleet": {f: len(v) for f, v in fleet.items()},
        "active_asset_ids": fleet,
        "families_in_assets": sorted(families),
        "not_active_vehicles": uncertain,
        "chargers_by_zone": chargers,
        "chargers_not_yet_active_by_zone": chargers_pending,
        "cash_eur": summary_cash, "pending_vehicle_payments_eur": round(pending, 2),
        "human_min_reserve_eur": human_reserve, "marketing_budget_limit_eur": mkt_limit,
        "marketing_committed_eur": mkt_committed,
        "sealed_services": APPROVED_SERVICES,
        "zone_catalog_path": cat_path, "area_zone_counts": {a: len(z) for a, z in area_zones.items()},
        "last_month_kpis": _plan_kpis(docs), "lost_demand_by_cause": _plan_lost(docs),
        "last_prices": _plan_last_prices(docs),
        "campaign_posted": _plan_campaign_posted(docs),
        "accredited_fault_asset_ids": _plan_accredited(docs) if phase >= 3 else [],
        "f3_advantages": _plan_f3(docs),
        "state_files_read": used,
        "warnings": [],
    }
    if not docs:
        ctx["warnings"].append("sin estado: llama get_company_state con summary, assets y results y vuelve a llamar plan_prepare_context()")
    if summary_cash is None:
        ctx["warnings"].append("caja no encontrada: se asume solo CASH_FLOOR_EUR disponible, sin cargadores nuevos")
    if not catalog:
        ctx["warnings"].append("catálogo de zonas no encontrado")
    return ctx


def _plan_ctx_arg(context_json):
    """Acepta el JSON devuelto por plan_prepare_context, una ruta, o vacío (usa output/plan_context.json)."""
    s = (context_json or "").strip()
    if s.startswith("{"):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    for p in (s, "output/plan_context.json"):
        d = _plan_load(p) if p else None
        if isinstance(d, dict):
            return d
    return _plan_context()


# ---------------------------------------------------------------- plan maths
def _plan_largest_remainder(total, weights):
    """Reparte 'total' enteros según weights {k: w}."""
    s = sum(weights.values())
    if total <= 0 or s <= 0:
        return {k: 0 for k in weights}
    raw = {k: total * w / s for k, w in weights.items()}
    out = {k: int(math.floor(v)) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[:total - sum(out.values())]:
        out[k] += 1
    return out


def _plan_area_counts(n, weights):
    """Vehículos por área: Altza y Aiete con mínimo 1; flotas pequeñas por prioridad."""
    areas = [a for a in PLAN_AREA_PRIORITY if a in weights]
    if n <= 0 or not areas:
        return {}
    if n <= len(areas):
        return {a: 1 for a in areas[:n]}
    fixed = {a: 1 for a in PLAN_EQUITY_AREAS if a in weights}
    for a in fixed:
        fixed[a] = max(1, int(n * weights[a] / sum(weights.values())))
    rest = _plan_largest_remainder(n - sum(fixed.values()), {a: w for a, w in weights.items() if a not in fixed})
    rest.update(fixed)
    return rest


def _plan_split_families(area_counts, fam_totals):
    """Patinetes primero en zonas densas (máx 70 % del área), bicis en el resto."""
    scooters = fam_totals.get("scooter", 0)
    per = {a: {} for a in area_counts}
    left = {a: c for a, c in area_counts.items()}
    order = [a for a in PLAN_DENSITY_ORDER if a in area_counts]
    for cap in (PLAN_SCOOTER_CAP_SHARE, 1.0):
        for a in order:
            take = min(scooters, int(math.floor(area_counts[a] * cap)) - per[a].get("scooter", 0))
            if take > 0:
                per[a]["scooter"] = per[a].get("scooter", 0) + take
                left[a] -= take
                scooters -= take
    others = [(f, n) for f, n in sorted(fam_totals.items()) if f != "scooter"]
    for f, n in others:
        for a in order:
            take = min(n, left[a])
            if take > 0:
                per[a][f] = per[a].get(f, 0) + take
                left[a] -= take
                n -= take
    return per


def _plan_pct(counts):
    """{zone: n} -> lista de allocation_pct que suma exactamente 100 (2 decimales)."""
    tot = sum(counts.values())
    items = [(z, n) for z, n in counts.items() if n > 0]
    if not tot or not items:
        return []
    pcts = [[z, round(100.0 * n / tot, 2)] for z, n in items]
    pcts[max(range(len(pcts)), key=lambda i: pcts[i][1])][1] = round(
        pcts[max(range(len(pcts)), key=lambda i: pcts[i][1])][1] + 100 - sum(p for _, p in pcts), 2)
    return [{"zone_id": z, "allocation_pct": p} for z, p in pcts]


def _plan_fares(ctx, reasons):
    prev = ctx.get("last_prices") or {}
    lost = ctx.get("lost_demand_by_cause") or {}
    kpis = ctx.get("last_month_kpis") or {}
    total_lost = sum(lost.values())
    reqs = kpis.get("requests") or (kpis.get("served", 0) + total_lost)
    factor = 1.0
    if total_lost and lost.get("competitor", 0) / total_lost > 0.4:
        factor = 1 - PLAN_FARE_STEP
        reasons.append("demanda perdida sobre todo ante competidores: tarifas -5 %")
    elif reqs and total_lost / reqs < 0.05 and kpis.get("served"):
        factor = 1 + PLAN_FARE_STEP / 2
        reasons.append("casi sin demanda perdida: tarifas +2,5 %")
    prices = []
    for sid in APPROVED_SERVICES:
        base = dict(PLAN_FARES.get(sid, {"base_fare": 3.0, "price_per_km": 1.0}))
        p = prev.get(sid) or {}
        if p.get("base_fare") and p.get("price_per_km") and factor != 1.0:
            base = {"base_fare": p["base_fare"], "price_per_km": p["price_per_km"]}
        b = min(max(base["base_fare"] * factor, PLAN_FARE_FLOOR["base"], FARE_BOUNDS["base"][0]), FARE_BOUNDS["base"][1])
        k = min(max(base["price_per_km"] * factor, PLAN_FARE_FLOOR["km"], FARE_BOUNDS["km"][0]), FARE_BOUNDS["km"][1])
        prices.append({"service_id": sid, "base_fare": round(b, 2), "price_per_km": round(k, 2)})
    return prices


def _plan_month_key(inv):
    """Adapta el nombre de la clave de mes y las claves admitidas al esquema real si existe."""
    sch = _plan_load(inv.get("submission_schema_path") or "sources/service_plan.schema.json")
    props, strict = None, False
    for node in _plan_walk(sch or {}):
        p = node.get("properties")
        if isinstance(p, dict) and "prices" in p and "fleet_distribution" in p:
            props, strict = set(p), node.get("additionalProperties") is False
            break
    key = "month_in_phase"
    if props is not None and key not in props:
        key = "month" if "month" in props else None
    absolute = False
    if key == "month":
        mx = next((n["properties"]["month"].get("maximum") for n in _plan_walk(sch or {})
                   if isinstance(n.get("properties"), dict) and isinstance(n["properties"].get("month"), dict)), None)
        absolute = mx is None or mx > 4
    return key, (props if strict else None), absolute


def _plan_build(ctx):
    inv = _plan_invoke()
    reasons = []
    mip = ctx.get("month_in_phase", 1)
    cash = ctx.get("cash_eur")
    pending = ctx.get("pending_vehicle_payments_eur") or 0.0
    mkt = ctx.get("marketing_committed_eur") or 0.0
    human = ctx.get("human_min_reserve_eur") or 0.0
    floor = max(CASH_FLOOR_EUR, human)
    charger_budget = max(0.0, (cash if cash is not None else 0.0) - pending - mkt - floor)
    fam_totals = {f: n for f, n in (ctx.get("active_fleet") or {}).items() if n > 0}
    n_total = sum(fam_totals.values())
    catalog, _ = _plan_catalog(inv)
    existing = {z: c for z, c in (ctx.get("chargers_by_zone") or {}).items()}

    # Adaptación de pesos por área con la demanda perdida del mes anterior (si viene desglosada).
    weights = {a: w for a, w in PLAN_AREA_WEIGHTS.items()
               if any(ak == a for ak, _ in catalog.values()) or not catalog}
    lost = ctx.get("lost_demand_by_cause") or {}
    extra_charger = sum(lost.values()) > 0 and lost.get("recharge", 0) / sum(lost.values()) > 0.15
    if extra_charger:
        reasons.append("demanda perdida por recarga >15 %: un cargador extra en el área con más flota")

    # Celdas ancla por área: primero las que ya tienen cargador, después las de más demanda.
    scores = _plan_cell_scores(inv, catalog) if catalog else {}
    def cells_for(area):
        zs = [z for z, (ak, _) in catalog.items()
              if ak == area and z not in (ctx.get("chargers_not_yet_active_by_zone") or {})]
        with_ch = sorted([z for z in zs if existing.get(z)], key=lambda z: -scores.get(z, 0))
        rest = sorted([z for z in zs if not existing.get(z)], key=lambda z: (-scores.get(z, 0), z))
        return with_ch + rest

    area_counts = _plan_area_counts(n_total, weights)
    if n_total == 0:
        reasons.append("sin flota activa este mes: plan válido con tarifas y sin distribución")
    # Cargadores: max(1, ceil(v/20)) por área en sus mejores celdas; si falta caja, se quitan áreas.
    plan_cells, new_ch, spent = {}, [], 0.0
    target_areas = list(area_counts) if n_total else []
    if n_total == 0 and pending > 0 and mip <= 3:
        target_areas = [a for a in PLAN_AREA_PRIORITY if a in weights]
        reasons.append("flota contratada pendiente: se preabren cargadores ancla si la caja lo permite")
    biggest = max(area_counts, key=area_counts.get) if area_counts else None
    for a in [x for x in PLAN_AREA_PRIORITY if x in target_areas]:
        cands = cells_for(a)
        if not cands:
            continue
        need = max(1, math.ceil(area_counts.get(a, 0) / PLAN_VEHICLES_PER_CHARGER))
        if extra_charger and a == biggest:
            need += 1
        min_cells = PLAN_MIN_CELLS.get(a, 1) if area_counts.get(a, 0) >= 2 else 1
        cells = cands[:min(PLAN_MAX_CELLS_PER_AREA, max(need, min_cells), len(cands))]
        # Cada celda usada necesita su propio cargador; los extra van rotando entre celdas.
        buy = [z for z in cells if not existing.get(z)]
        extra = need - sum(existing.get(z, 0) for z in cells) - len(buy)
        buy += [cells[i % len(cells)] for i in range(max(0, extra))]
        wanted = len(buy)
        affordable = int(max(0.0, charger_budget - spent) // CHARGER_COST_EUR)
        if wanted > affordable:
            buy = buy[:affordable]
            reasons.append(f"caja limitada: {a} recibe {len(buy)} de {wanted} cargadores nuevos")
        spent += CHARGER_COST_EUR * len(buy)
        for z, c in [(z, 1) for z in buy]:
            existing_new = next((x for x in new_ch if x["zone_id"] == z), None)
            if existing_new:
                existing_new["chargers"] += c
            else:
                new_ch.append({"zone_id": z, "chargers": c, "month_in_phase": mip})
        live = [z for z in cells if existing.get(z) or any(x["zone_id"] == z for x in new_ch)]
        if live:
            plan_cells[a] = live

    # Áreas sin cargador posible: su flota se reasigna al resto.
    if n_total and set(area_counts) - set(plan_cells):
        dropped = sorted(set(area_counts) - set(plan_cells))
        reasons.append(f"áreas sin cargador (caja o catálogo): {dropped}; flota reasignada")
        w2 = {a: w for a, w in weights.items() if a in plan_cells}
        area_counts = _plan_area_counts(n_total, w2) if w2 else {}
    if n_total and not plan_cells:
        reasons.append("ninguna zona con cargador activo posible: flota sin distribuir este mes")

    per_area = _plan_split_families(area_counts, fam_totals) if plan_cells else {}
    fleet_distribution = []
    for fam in sorted(fam_totals):
        counts = {}
        for a, fams in per_area.items():
            cells = plan_cells.get(a, [])
            if not cells or not fams.get(fam):
                continue
            for z, c in _plan_largest_remainder(fams[fam], {z: 1 for z in cells}).items():
                counts[z] = counts.get(z, 0) + c
        zones = _plan_pct(counts)
        if zones:
            fleet_distribution.append({"product_id": fam, "zones": zones})
    # Familias presentes en activos pero sin unidades activas: misma forma (inocuo, evita flota parada si
    # el estado usa otro status).
    shape = {}
    for fd in fleet_distribution:
        for z in fd["zones"]:
            shape[z["zone_id"]] = shape.get(z["zone_id"], 0) + z["allocation_pct"]
    for fam in ctx.get("families_in_assets") or []:
        if fam not in fam_totals and fam in ("bike", "scooter") and shape:
            fleet_distribution.append({"product_id": fam, "zones": _plan_pct(
                {z: int(round(v * 100)) for z, v in shape.items()})})

    reserve = 0.0 if cash is None else max(0.0, min(floor, cash - pending - mkt - spent))
    # Estructura del esquema real (sources/service_plan.schema.json):
    # months[0] = {month_in_phase, prices, service_mode, service_allocations, fleet_distribution};
    # charging_investments y reserve_cash van en la RAÍZ del plan.
    fleet_distribution = [fd for fd in fleet_distribution if fd.get("zones")]
    month = {"month_in_phase": int(mip), "prices": _plan_fares(ctx, reasons), "service_mode": "pooled",
             "service_allocations": [], "fleet_distribution": fleet_distribution}
    invest = [{"zone_id": str(c["zone_id"]), "chargers": int(c.get("chargers", 1) or 1), "month_in_phase": int(mip)}
              for c in new_ch]
    reasons.append(f"flota activa {fam_totals or 0}, áreas {dict(area_counts)}, "
                   f"cargadores nuevos {len(new_ch)} ({spent:.0f} EUR), reserva {reserve:.0f} EUR")
    return ({"months": [month], "charging_investments": invest, "reserve_cash": round(reserve, 2)},
            sorted(existing), reasons)


# ---------------------------------------------------------------- validation
def _plan_business_errors(plan, charger_zone_ids=(), catalog=None, cash_ctx=None):
    errs = []
    months = plan.get("months")
    if not isinstance(months, list) or len(months) != 1:
        return ["months debe contener exactamente un objeto (mes actual)"]
    m = months[0]
    services = sorted(p.get("service_id") for p in m.get("prices", []))
    if services != sorted(APPROVED_SERVICES):
        errs.append(f"prices debe cubrir exactamente {APPROVED_SERVICES}, tiene {services}")
    for p in m.get("prices", []):
        if not FARE_BOUNDS["base"][0] <= (_plan_num(p.get("base_fare")) or -1) <= FARE_BOUNDS["base"][1]:
            errs.append(f"base_fare fuera de rango: {p.get('base_fare')}")
        if not FARE_BOUNDS["km"][0] <= (_plan_num(p.get("price_per_km")) or -1) <= FARE_BOUNDS["km"][1]:
            errs.append(f"price_per_km fuera de rango: {p.get('price_per_km')}")
    invest = plan.get("charging_investments", m.get("charging_investments", [])) or []
    chargers = set(charger_zone_ids) | {c["zone_id"] for c in invest if c.get("chargers", 0) > 0}
    for fd in m.get("fleet_distribution", []):
        if fd.get("product_id") not in ("bike", "scooter", "drone"):
            errs.append(f"product_id debe ser la familia (bike/scooter/drone): {fd.get('product_id')}")
        s = sum(z.get("allocation_pct", 0) for z in fd.get("zones", []))
        if fd.get("zones") and not math.isclose(s, 100, abs_tol=0.01):
            errs.append(f"fleet_distribution {fd.get('product_id')} suma {s}")
        for z in fd.get("zones", []):
            if z.get("allocation_pct", 0) > 0 and z["zone_id"] not in chargers:
                errs.append(f"zona {z['zone_id']} con flota sin cargador activo")
            if catalog and z.get("zone_id") not in catalog:
                errs.append(f"zone_id desconocido en el catálogo: {z.get('zone_id')}")
    for c in invest:
        if catalog and c.get("zone_id") not in catalog:
            errs.append(f"cargador en zone_id desconocido: {c.get('zone_id')}")
    if m.get("service_mode", "dedicated") == "pooled" and m.get("service_allocations"):
        errs.append("pooled exige service_allocations vacío")
    for sa in m.get("service_allocations", []):
        s = sum(x.get("allocation_pct", 0) for x in sa.get("services", []))
        if not math.isclose(s, 100, abs_tol=0.01):
            errs.append(f"service_allocations {sa.get('product_id')} suma {s}")
    if m.get("month_in_phase") is None:
        errs.append("months[0].month_in_phase es obligatorio")
    errs += _common_schema_file_errors(["sources/service_plan.schema.json"], plan)
    if cash_ctx and cash_ctx.get("cash_eur") is not None:
        spend = CHARGER_COST_EUR * sum(c.get("chargers", 0) for c in invest)
        need = (spend + (cash_ctx.get("marketing_committed_eur") or 0)
                + (cash_ctx.get("pending_vehicle_payments_eur") or 0)
                + max(plan.get("reserve_cash", m.get("reserve_cash", 0)) or 0, cash_ctx.get("human_min_reserve_eur") or 0))
        if spend > 0 and need > cash_ctx["cash_eur"] + 0.01:
            errs.append(f"regla de caja: compromisos {need:.0f} > caja {cash_ctx['cash_eur']:.0f}")
    return errs


# ---------------------------------------------------------------- maintenance + marketing maths
def _plan_maintenance(ctx):
    acts, reasons = [], []
    accredited = list(ctx.get("accredited_fault_asset_ids") or [])
    f3 = ctx.get("f3_advantages") or {}
    if ctx.get("phase", 1) >= 3 and f3.get("verified_faults", 0) > 0 and not accredited:
        # Con fallos acreditados la reparación sale muy barata (+salud, +calidad, menos desgaste):
        # se repara una vez cada vehículo activo aún no reparado en esta fase.
        done = set(f3.get("repaired_asset_ids") or [])
        accredited = [a for ids in (ctx.get("active_asset_ids") or {}).values() for a in ids if a not in done]
    for aid in accredited:
        acts.append({"asset_id": aid, "action": "repair"})
    if accredited:
        reasons.append(f"reparación de {len(accredited)} vehículos con fallo acreditado")
    active = [a for ids in (ctx.get("active_asset_ids") or {}).values() for a in ids if a not in accredited]
    cash = ctx.get("cash_eur")
    spare = (cash or 0) - (ctx.get("pending_vehicle_payments_eur") or 0) - CASH_FLOOR_EUR - PLAN_MAINT_BUFFER_EUR
    cal_cost = PLAN_MAINT_COST["calibrate"] * len(active)
    if active and not accredited and ctx.get("month_in_phase", 1) in (1, 3) and spare >= cal_cost + PLAN_MAINT_COST["repair"] * len(accredited):
        acts += [{"asset_id": a, "action": "calibrate"} for a in active]
        reasons.append(f"ajuste (calibrate) de {len(active)} vehículos: +1,5 calidad 2 meses por {cal_cost} EUR")
    mult = (ctx.get("f3_advantages") or {}).get("cost_multiplier") or 1.0
    total = round(sum(PLAN_MAINT_COST[a["action"]] * (mult if a["action"] == "repair" else 1.0) for a in acts) + 1, 2)
    if not acts:
        return {"actions": []}, reasons + ["sin acciones de mantenimiento este mes"]
    return {"actions": acts, "max_total_cost": total}, reasons


def _mkt_reference():
    """Canales y segmentos de marketing/reference/* (csv/json/md); fallback si no hay archivos."""
    channels, segments = [], []
    roots = [Path("marketing/reference"), Path("marketing"), Path("sources/marketing")]
    for root in roots:
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.stat().st_size > 5_000_000:
                continue
            if p.suffix == ".csv":
                import csv
                with open(p, encoding="utf-8-sig", newline="") as f:
                    for r in csv.DictReader(f):
                        for k, v in r.items():
                            lk = (k or "").lower()
                            if v and lk in ("channel", "channel_id", "canal", "medium", "medio"):
                                channels.append(v.strip())
                            if v and lk in ("segment", "segment_id", "customer_segment", "audience", "target_segment", "publico"):
                                segments.append(v.strip())
            elif p.suffix == ".json":
                for node in _plan_walk(_plan_load(p) or {}):
                    for k in ("channel", "channel_id"):
                        if isinstance(node.get(k), str):
                            channels.append(node[k])
                    for k in ("segment", "segment_id", "customer_segment"):
                        if isinstance(node.get(k), str):
                            segments.append(node[k])
        if channels:
            break
    uniq = lambda xs: list(dict.fromkeys(x for x in xs if x))
    return uniq(channels), uniq(segments)


def _mkt_eur(x):
    return f"{x:.2f}".replace(".", ",")


def _mkt_pick(channels, prefs, exclude=()):
    best, score = None, -1
    for c in channels:
        if c in exclude:
            continue
        s = sum(1 for w in prefs if w in c.lower())
        if s > score:
            best, score = c, s
    return best


def _mkt_campaign(ctx):
    reasons = []
    opt = lambda why: ({"objective": "No invertir en marketing este cuatrimestre", "campaigns": [],
                        "opt_out_reason": why}, reasons + [why])
    if ctx.get("phase") != 2:
        return opt("El marketing solo se decide en la fase 2")
    fleet = sum((ctx.get("active_fleet") or {}).values())
    if fleet == 0 and not ctx.get("pending_vehicle_payments_eur"):
        return opt("Sin flota activa ni entregas pendientes: la publicidad no se podría atender")
    lost = ctx.get("lost_demand_by_cause") or {}
    kpis = ctx.get("last_month_kpis") or {}
    reqs = kpis.get("requests") or (kpis.get("served", 0) + sum(lost.values()))
    cap_lost = lost.get("no_vehicle", 0) + lost.get("busy", 0) + lost.get("recharge", 0)
    if reqs and cap_lost / reqs > MKT_SATURATION_LOST_SHARE:
        return opt("Flota saturada: más del 25 % de la demanda se pierde por falta de vehículo o recarga")
    cash = ctx.get("cash_eur")
    budget = MKT_MAX_BUDGET_EUR
    if ctx.get("marketing_budget_limit_eur") is not None:
        budget = min(budget, ctx["marketing_budget_limit_eur"])
    if cash is not None:
        budget = min(budget, cash - (ctx.get("pending_vehicle_payments_eur") or 0) - CASH_FLOOR_EUR)
    budget = int(budget // 100 * 100)
    if budget < MKT_MIN_BUDGET_EUR:
        return opt("Caja insuficiente sobre la reserva mínima para una campaña útil")
    channels, segments = _mkt_reference()
    if not channels:
        channels = list(MKT_FALLBACK_CHANNELS)
        reasons.append("marketing/reference sin canales legibles: canales por defecto")
    seg = lambda s: s if (not segments or s in segments) else None
    young, adults = seg("young") or (segments[0] if segments else "young"), seg("adults")
    pax = next((p for p in _plan_fares(ctx, []) if p["service_id"] == "passenger_transport"), {})
    ch1 = _mkt_pick(channels, MKT_CHANNEL_PREF["young"])
    ch2 = _mkt_pick(channels, MKT_CHANNEL_PREF["food"], exclude=(ch1,)) or ch1
    start = (ctx.get("month_in_phase", 1) - 1) * 4 + 1
    b1 = int(budget * 0.6 // 50 * 50)
    campaigns = [
        {"channel": ch1, "budget": b1, "target_segments": [young],
         "target_services": ["passenger_transport"],
         "message": (f"Bici autónoma entre Gros y el campus de Ibaeta en unos 15 minutos. "
                     f"Ves el precio final antes de pedir: desde {_mkt_eur(pax.get('base_fare', 2.95))} € "
                     f"de bajada y {_mkt_eur(pax.get('price_per_km', 0.98))} €/km."),
         "frequency_per_week": 2, "start_week": start, "end_week": 16,
         "call_to_action": "Pide tu bici en la app de urbAIn antes de clase"},
        {"channel": ch2, "budget": budget - b1, "target_segments": [s for s in (young, adults) if s],
         "target_services": ["food_delivery"],
         "message": ("Cena en casa de 20 a 23 h: reparto autónomo en Centro, Gros y Antiguo, "
                     "con el precio total cerrado antes de pedir y tarifa baja en pedidos pequeños."),
         "frequency_per_week": 2, "start_week": start, "end_week": 16,
         "call_to_action": "Haz tu pedido de cena en la app de urbAIn"},
    ]
    margin = 2.1
    reasons.append(f"presupuesto {budget} EUR; equilibrio ≈ {math.ceil(budget / margin)} servicios extra "
                   f"en {17 - start} semanas; canales {ch1}, {ch2}")
    return {"objective": "Captar estudiantes (Gros - campus) y cenas a domicilio con flota con capacidad libre",
            "campaigns": campaigns}, reasons


# ---------------------------------------------------------------- tools
@tool
def plan_prepare_context(response_paths_json: str = "[]") -> str:
    """Prepara el contexto del mes leyendo solas las respuestas de get_company_state ya llamadas (summary, assets, results), el catálogo de zonas y la fase/mes. Llámala DESPUÉS de get_company_state. response_paths_json es opcional."""
    try:
        paths = json.loads(response_paths_json or "[]")
    except json.JSONDecodeError:
        paths = []
    ctx = _plan_context(paths if isinstance(paths, list) else [])
    Path("output").mkdir(exist_ok=True)
    Path("output/plan_context.json").write_text(json.dumps(ctx, ensure_ascii=False), encoding="utf-8")
    compact = {k: v for k, v in ctx.items() if k != "active_asset_ids"}
    compact["context_path"] = "output/plan_context.json"
    return json.dumps(compact, ensure_ascii=False)[:12000]


def _plan_build_safe(ctx):
    """Plan determinista con caídas seguras. Devuelve (plan, errores, cargadores existentes, motivos)."""
    catalog, _ = _plan_catalog(_plan_invoke())
    plan, chargers, reasons = _plan_build(ctx)
    errs = _plan_business_errors(plan, chargers, catalog or None, ctx)
    if errs:
        reasons.append(f"plan principal inválido {errs[:3]}: se usa plan sin cargadores nuevos")
        plan, chargers, more = _plan_build(dict(ctx, cash_eur=0.0, pending_vehicle_payments_eur=0.0))
        reasons += more
        errs = _plan_business_errors(plan, chargers, catalog or None, ctx)
    if errs:
        reasons.append(f"plan sin cargadores inválido {errs[:3]}: se envía solo tarifas")
        m = plan["months"][0]
        m["fleet_distribution"], m["service_allocations"] = [], []
        plan["charging_investments"], plan["reserve_cash"] = [], 0.0
        errs = _plan_business_errors(plan, chargers, catalog or None, ctx)
    return plan, errs, chargers, reasons


def _plan_fresh_ctx(context_json=""):
    """Contexto recalculado en ESTA llamada (los archivos de otras herramientas no persisten entre llamadas)."""
    s = (context_json or "").strip()
    if s.startswith("{"):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    return _plan_context()


@tool
def plan_build(context_json: str = "") -> str:
    """Vista previa (opcional): calcula y valida el plan del mes y explica los motivos. No envía nada. Para entregar usa plan_submit()."""
    ctx = _plan_fresh_ctx(context_json)
    plan, errs, chargers, reasons = _plan_build_safe(ctx)
    return json.dumps({"valid": not errs, "errors": errs, "existing_charger_zone_ids": chargers,
                       "plan": plan, "reasons": reasons,
                       "next": "Llama plan_submit() sin argumentos para entregarlo."}, ensure_ascii=False)[:12000]


@tool
def plan_build_maintenance(context_json: str = "") -> str:
    """Calcula el plan de mantenimiento del mes: repair para fallos acreditados (F3) y calibrate cuando es barato. Devuelve {actions, max_total_cost} o {actions: []}. Úsala antes de plan_submit_fleet_maintenance."""
    plan, reasons = _plan_maintenance(_plan_ctx_arg(context_json))
    return json.dumps({"maintenance_json": plan, "submit": bool(plan["actions"]), "reasons": reasons},
                      ensure_ascii=False)


@tool
def mkt_build_campaign(context_json: str = "") -> str:
    """F2: calcula la campaña de marketing (≤3.000 €, canales de marketing/reference, mensajes creíbles con llamada a la acción) o una renuncia válida. Úsala antes de mkt_post_campaigns."""
    camp, reasons = _mkt_campaign(_plan_ctx_arg(context_json))
    Path("output").mkdir(exist_ok=True)
    Path("output/mkt_campaign.json").write_text(json.dumps(camp, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.dumps({"campaign_json": camp, "reasons": reasons}, ensure_ascii=False)


@tool
def plan_validate(plan_json: str = "", existing_charger_zone_ids_json: str = "[]", plan_path: str = "") -> str:
    """Valida el plan mensual (servicios, tarifas, sumas, cargadores, zonas del catálogo, caja) y, si es válido, lo guarda en output/plan_validado.json. Úsala SIEMPRE antes de plan_submit; con plan_path='output/plan_borrador.json' no hace falta copiar el JSON."""
    try:
        plan = json.loads(plan_json) if (plan_json or "").strip() else _plan_load(plan_path or "output/plan_borrador.json")
        chargers = json.loads(existing_charger_zone_ids_json or "[]")
    except json.JSONDecodeError as e:
        return json.dumps({"valid": False, "errors": [f"JSON inválido: {e}"]}, ensure_ascii=False)
    if not isinstance(plan, dict):
        return json.dumps({"valid": False, "errors": ["plan no encontrado"]}, ensure_ascii=False)
    ctx = _plan_load("output/plan_context.json") or {}
    chargers = set(chargers) | set((ctx.get("chargers_by_zone") or {}).keys())
    catalog, _ = _plan_catalog(_plan_invoke())
    errs = _plan_business_errors(plan, chargers, catalog or None, ctx)
    if errs:
        return json.dumps({"valid": False, "errors": errs}, ensure_ascii=False)
    Path("output").mkdir(exist_ok=True)
    path = Path("output") / "plan_validado.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.dumps({"valid": True, "plan_path": str(path)})


@tool
def plan_submit(plan_path: str = "") -> dict:
    """ENTREGA OFICIAL del plan del mes (POST phase-decisions, una sola vez). Recalcula y valida el plan en esta misma llamada a partir de las respuestas de get_company_state (summary, assets, results). Llámala SIN argumentos."""
    ctx = _plan_fresh_ctx("")
    plan, errs, _, reasons = _plan_build_safe(ctx)
    if errs:
        return {"error": "plan inválido, no enviado", "details": errs, "reasons": reasons, "api_called": False}
    return request("POST", "/api/v1/service/teams/{team_id}/phase-decisions", body=plan)


@tool
def plan_submit_fleet_maintenance(plan_json: str = "") -> dict:
    """Opcional, una vez al mes y ANTES de plan_submit (F3: repara vehículos con fallos acreditados). Sin argumentos calcula el plan de mantenimiento en esta misma llamada; si no hay acciones, no envía nada."""
    body = None
    if (plan_json or "").strip():
        try:
            body = json.loads(plan_json)
        except json.JSONDecodeError as e:
            return {"error": f"JSON inválido: {e}"}
        if isinstance(body, dict) and "maintenance_json" in body:
            body = body["maintenance_json"]
    if body is None:
        body, _ = _plan_maintenance(_plan_fresh_ctx(""))
    if not isinstance(body, dict) or not body.get("actions"):
        return {"skipped": True, "reason": "sin acciones de mantenimiento: no se envía nada"}
    errs = _common_schema_file_errors(["referencia/contratos_api/service_maintenance.schema.json",
                                       "sources/service_maintenance.schema.json"], body)
    if errs:
        return {"error": "plan de mantenimiento inválido, no enviado", "details": errs[:8], "api_called": False}
    return request("POST", "/api/v1/service/teams/{team_id}/maintenance-plan", body=body)


@tool
def plan_list_tenders() -> dict:
    """Lista encargos públicos de servicios (opcionales). Úsala solo si hay capacidad libre."""
    return request("GET", "/api/v1/service/teams/{team_id}/tenders")


@tool
def mkt_post_campaigns(campaign_json: str = "") -> dict:
    """F2: publica la campaña (máx. 3.000 €/fase) ANTES del plan, o registra campaigns=[] con opt_out_reason. Sin argumentos la calcula en esta misma llamada."""
    try:
        body = json.loads(campaign_json) if (campaign_json or "").strip() else _mkt_campaign(_plan_fresh_ctx(""))[0]
    except json.JSONDecodeError as e:
        return {"error": f"JSON inválido: {e}"}
    if not isinstance(body, dict):
        return {"error": "campaña no encontrada: ejecuta mkt_build_campaign"}
    errs = _common_schema_file_errors(["marketing/reference/campaign.schema.json"], body)
    if errs:
        return {"error": "campaña inválida según el esquema, no enviada", "details": errs[:8], "api_called": False}
    total = sum(c.get("budget", 0) for c in body.get("campaigns", []))
    if total > MKT_MAX_BUDGET_EUR or (not body.get("campaigns") and not body.get("opt_out_reason")):
        return {"error": "campaña inválida: presupuesto >3.000 € o renuncia sin opt_out_reason"}
    return request("POST", "/api/v1/service/teams/{team_id}/marketing-campaigns", body=body)


PLAN_TOOLS = [plan_prepare_context, plan_build, plan_submit, plan_submit_fleet_maintenance,
              plan_list_tenders, mkt_build_campaign, mkt_post_campaigns]
