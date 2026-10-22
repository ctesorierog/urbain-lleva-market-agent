# test_plan.py · OWNER: Carlos · fixtures for plan + marketing + maintenance tools
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
if "studio" not in sys.modules:
    sys.modules["studio"] = types.SimpleNamespace(tool=lambda f: f)
if "simulator" not in sys.modules:
    sys.modules["simulator"] = types.SimpleNamespace(
        request=lambda method, path, params=None, body=None: {"method": method, "path": path, "body": body})

import tools_plan as tp  # noqa: E402

AREAS = {"Centro + Parte Vieja": "c", "Gros + Zurriola + Ategorrieta": "g", "Amara + Egia + Loiola + Riberas": "m",
         "Antiguo + Ondarreta + Ibaeta": "a", "Altza + Intxaurrondo + Bidebieta + Herrera": "z", "Aiete": "e",
         "Igara + Zuatzu": "i"}


def _vehicles(n_bike, n_scooter, activation=1):
    vs = [{"asset_id": f"veh-b{i}", "product_id": "bike", "variant_id": "bike:high_low",
           "status": "active", "activation_month": activation} for i in range(n_bike)]
    vs += [{"asset_id": f"veh-s{i}", "product_id": "scooter", "status": "active",
            "activation_month": activation} for i in range(n_scooter)]
    return vs


def _workspace(tmp_path, monkeypatch, vehicles=(), chargers=(), cash=500000, pending=0, phase=1, month=1,
               extra_state=None, marketing_ref=True):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "input").mkdir()
    (tmp_path / "mercado").mkdir()
    zones = ["zone_id,market_area"] + [f"z{code}{i},{area}" for area, code in AREAS.items() for i in range(3)]
    (tmp_path / "mercado/zonas.csv").write_text("\n".join(zones), encoding="utf-8")
    rows = ["request_id,service_id,customer_segment,origin_h3,destination_h3"]
    for area, code in AREAS.items():
        for i, n in enumerate((5, 3, 1)):
            rows += [f"r{code}{i}{k},passenger_transport,adults,z{code}{i},zc0" for k in range(n)]
    (tmp_path / "mercado/historico_demanda.csv").write_text("\n".join(rows), encoding="utf-8")
    state = {"summary": {"cash_eur": cash, "pending_vehicle_payments_eur": pending},
             "assets": {"vehicles": list(vehicles), "chargers": list(chargers)}}
    state.update(extra_state or {})
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    inv = {"phase": phase, "month_in_phase": month, "state_path": "state.json",
           "zone_catalog_path": "mercado/zonas.csv", "demand_history_path": "mercado/historico_demanda.csv"}
    (tmp_path / "input/invoke.json").write_text(json.dumps(inv), encoding="utf-8")
    if marketing_ref:
        (tmp_path / "marketing/reference").mkdir(parents=True)
        (tmp_path / "marketing/reference/canales.csv").write_text(
            "channel_id,segment,audience_k\nsocial,young,40\nsearch,adults,30\npartners,young,10\n"
            "radio,seniors,20\nprint,tourists,5\n", encoding="utf-8")


def _run_plan():
    ctx = json.loads(tp.plan_prepare_context())
    built = json.loads(tp.plan_build(""))
    val = json.loads(tp.plan_validate(plan_path=built["plan_path"],
                                      existing_charger_zone_ids_json=json.dumps(built["existing_charger_zone_ids"])))
    return ctx, built, val


def test_normal_month_valid_and_equity(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch, vehicles=_vehicles(24, 10))
    ctx, built, val = _run_plan()
    assert ctx["active_fleet"] == {"bike": 24, "scooter": 10}
    assert val["valid"], val
    m = built["plan"]["months"][0]
    assert m["service_mode"] == "pooled" and m["service_allocations"] == []
    zones_with_fleet = {z["zone_id"] for fd in m["fleet_distribution"] for z in fd["zones"]}
    assert any(z.startswith("zz") for z in zones_with_fleet) and any(z.startswith("ze") for z in zones_with_fleet)
    assert not any(z.startswith("zi") for z in zones_with_fleet)  # Igara not targeted
    assert {c["zone_id"] for c in m["charging_investments"]} >= zones_with_fleet
    assert "zc0" in zones_with_fleet  # top-demand cell is the Centro anchor
    assert m["reserve_cash"] >= tp.CASH_FLOOR_EUR


def test_zero_fleet_still_valid(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    _, built, val = _run_plan()
    assert val["valid"]
    m = built["plan"]["months"][0]
    assert m["fleet_distribution"] == [] and len(m["prices"]) == 2


def test_delayed_delivery_not_counted(tmp_path, monkeypatch):
    late = _vehicles(5, 0, activation=3)
    contracted = [{"asset_id": "c1", "product_id": "bike", "status": "pending_delivery"}]
    _workspace(tmp_path, monkeypatch, vehicles=late + contracted + _vehicles(0, 2), month=2)
    ctx, _, val = _run_plan()
    assert ctx["active_fleet"] == {"scooter": 2} and val["valid"]


def test_low_cash_no_new_chargers(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch, vehicles=_vehicles(10, 0), cash=65000)
    _, built, val = _run_plan()
    m = built["plan"]["months"][0]
    assert val["valid"], val
    assert m["charging_investments"] == [] and m["fleet_distribution"] == []


def test_existing_charger_reused_and_scarce_cash(tmp_path, monkeypatch):
    ch = [{"asset_id": "chg-1", "asset_type": "charger", "zone_id": "zg1", "status": "active"}]
    _workspace(tmp_path, monkeypatch, vehicles=_vehicles(12, 0), chargers=ch, cash=60000 + 2 * 6000)
    _, built, val = _run_plan()
    m = built["plan"]["months"][0]
    assert val["valid"], val
    assert len(m["charging_investments"]) == 2
    zones = {z["zone_id"] for fd in m["fleet_distribution"] for z in fd["zones"]}
    assert "zg1" in zones and not any(c["zone_id"] == "zg1" for c in m["charging_investments"])


def test_validator_rejects_bad_plans(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch, vehicles=_vehicles(6, 0))
    _, built, _ = _run_plan()
    plan = built["plan"]
    bad = json.loads(json.dumps(plan))
    bad["months"][0]["prices"].append({"service_id": "package_delivery", "base_fare": 3, "price_per_km": 1})
    assert not json.loads(tp.plan_validate(json.dumps(bad)))["valid"]
    bad = json.loads(json.dumps(plan))
    bad["months"][0]["prices"][0]["base_fare"] = 5.5
    assert not json.loads(tp.plan_validate(json.dumps(bad)))["valid"]
    bad = json.loads(json.dumps(plan))
    bad["months"][0]["charging_investments"] = []
    assert "sin cargador" in tp.plan_validate(json.dumps(bad))
    bad = json.loads(json.dumps(plan))
    bad["months"][0]["fleet_distribution"][0]["product_id"] = "bike:high_low"
    assert not json.loads(tp.plan_validate(json.dumps(bad)))["valid"]
    assert "error" in tp.plan_submit("output/plan_borrador.json")


def test_marketing_campaign_f2(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch, vehicles=_vehicles(20, 6), phase=2, month=1)
    tp.plan_prepare_context()
    out = json.loads(tp.mkt_build_campaign(""))
    camp = out["campaign_json"]["campaigns"]
    assert 0 < sum(c["budget"] for c in camp) <= 3000
    assert {c["channel"] for c in camp} <= {"social", "search", "partners", "radio", "print"}
    assert all(c["call_to_action"] and 1 <= c["frequency_per_week"] <= 3 and c["start_week"] == 1 for c in camp)
    assert tp.mkt_post_campaigns("")["path"].endswith("marketing-campaigns")


def test_marketing_opt_out_without_fleet_and_saturated(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch, phase=2)
    tp.plan_prepare_context()
    c = json.loads(tp.mkt_build_campaign(""))["campaign_json"]
    assert c["campaigns"] == [] and c["opt_out_reason"]
    assert tp.mkt_post_campaigns("")["path"].endswith("marketing-campaigns")


def test_marketing_opt_out_saturated(tmp_path, monkeypatch):
    res = {"results": {"served_requests": 3000, "total_requests": 5000,
                       "lost_demand": {"no_vehicle_available": 1500, "competitor": 500}}}
    _workspace(tmp_path, monkeypatch, vehicles=_vehicles(10, 0), phase=2, month=2, extra_state=res)
    ctx = json.loads(tp.plan_prepare_context())
    assert ctx["lost_demand_by_cause"]["no_vehicle"] == 1500
    c = json.loads(tp.mkt_build_campaign(""))["campaign_json"]
    assert c["campaigns"] == [] and "saturada" in c["opt_out_reason"]


def test_f3_repair_loop(tmp_path, monkeypatch):
    effects = {"maintenance_effects": [{"asset_id": "veh-b1", "status": "accredited", "alert_id": "AV-001"},
                                       {"asset_id": "veh-b2", "status": "rejected"}]}
    _workspace(tmp_path, monkeypatch, vehicles=_vehicles(4, 0), phase=3, month=2, extra_state=effects)
    ctx = json.loads(tp.plan_prepare_context())
    assert ctx["accredited_fault_asset_ids"] == ["veh-b1"]
    m = json.loads(tp.plan_build_maintenance(""))
    assert m["submit"] and m["maintenance_json"]["actions"] == [{"asset_id": "veh-b1", "action": "repair"}]
    assert m["maintenance_json"]["max_total_cost"] == 90
    assert tp.plan_submit_fleet_maintenance(json.dumps({"actions": []}))["skipped"]


def test_small_fleet_round_trip_counts(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch, vehicles=_vehicles(3, 1))
    _, built, val = _run_plan()
    assert val["valid"]
    m = built["plan"]["months"][0]
    for fd in m["fleet_distribution"]:
        assert abs(sum(z["allocation_pct"] for z in fd["zones"]) - 100) < 0.01


def test_charger_not_yet_active_is_not_used(tmp_path, monkeypatch):
    ch = [{"asset_id": "chg-9", "asset_type": "charger", "zone_id": "zc0", "status": "installed",
           "activation_month": 2}]
    _workspace(tmp_path, monkeypatch, vehicles=_vehicles(8, 0), chargers=ch)
    ctx, built, val = _run_plan()
    assert ctx["chargers_not_yet_active_by_zone"] == {"zc0": 1} and val["valid"]
    zones = {z["zone_id"] for fd in built["plan"]["months"][0]["fleet_distribution"] for z in fd["zones"]}
    assert "zc0" not in zones


def test_idle_status_counts_and_contract_is_not_fleet(tmp_path, monkeypatch):
    idle = [{"asset_id": f"veh-i{i}", "product_id": "bike", "status": "idle"} for i in range(6)]
    contract = [{"id": "ctr-1", "product_id": "bike", "status": "active", "quantity": 20}]
    _workspace(tmp_path, monkeypatch, vehicles=idle + contract)
    ctx, built, val = _run_plan()
    assert ctx["active_fleet"] == {"bike": 6} and val["valid"]


def test_low_cash_below_pending_still_submits(tmp_path, monkeypatch):
    ch = [{"asset_id": "chg-1", "asset_type": "charger", "zone_id": "zg0", "status": "active"}]
    _workspace(tmp_path, monkeypatch, vehicles=_vehicles(5, 0), chargers=ch, cash=40000, pending=50000)
    _, built, val = _run_plan()
    assert built["valid"] and val["valid"], (built["errors"], val)
    m = built["plan"]["months"][0]
    assert m["charging_investments"] == [] and m["reserve_cash"] == 0
    assert {z["zone_id"] for fd in m["fleet_distribution"] for z in fd["zones"]} == {"zg0"}


def test_charger_not_double_counted(tmp_path, monkeypatch):
    ch = [{"asset_id": "chg-1", "asset_type": "charger", "zone_id": "zc0", "status": "active"},
          {"zone_id": "zc0", "chargers": 1, "charging_option_id": "standard", "id": "agg"}]
    _workspace(tmp_path, monkeypatch, vehicles=_vehicles(4, 0), chargers=ch)
    ctx = json.loads(tp.plan_prepare_context())
    assert ctx["chargers_by_zone"] == {"zc0": 1}


def test_phase_relative_activation(tmp_path, monkeypatch):
    v = [{"asset_id": "b1", "product_id": "bike", "status": "received", "activation_month": "M7"},
         {"asset_id": "b2", "product_id": "bike", "status": "received", "activation_month": 5}]
    _workspace(tmp_path, monkeypatch, vehicles=v, phase=2, month=1)
    ctx = json.loads(tp.plan_prepare_context())
    assert ctx["active_fleet"] == {"bike": 1}
