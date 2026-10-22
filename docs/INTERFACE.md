# INTERFACE.md · urbAIn team contract (Carlos ⇄ Luca)

> Both coding assistants read this file. It is the only agreement on names, files and connections. Do not rename anything here without telling the other person. If a change is needed, write it under "Change requests" at the bottom and tell your teammate.

## 1. Who owns what

| Owner | Track | Files you may edit | Platform tasks covered |
|---|---|---|---|
| **Carlos** (integrator) | Service plan + marketing | `agent/main.py`, `agent/tools_common.py`, `agent/tools_plan.py`, `agent/playbooks/core.md`, `agent/playbooks/plan.md`, `agent/playbooks/marketing.md`, `tests/test_plan.py`, `tests/test_common.py`, `scripts/merge.py` | monthly service plan M1–M12, fleet maintenance, tenders, F2 marketing |
| **Luca** | Negotiation + diagnosis | `agent/tools_nego.py`, `agent/playbooks/negotiation.md`, `agent/playbooks/diagnosis.md`, `tests/test_nego.py`, `tests/test_diag.py`, `tests/fixtures/nego_*.json`, `tests/fixtures/diag_*` | negotiation turns F1–F3, F3 fault diagnosis |

**Never edit a file you don't own.** If you need something from `tools_common.py`, request it (section 9).

## 2. Repo layout (identical on both laptops)
```
urbAIn_kit/
  CONTEXT.md          rules, scoring, APIs (shared truth)
  INTERFACE.md        this file
  data/               market CSVs for offline analysis (NOT available to the agent at run time)
  agent/
    main.py           Carlos · build_agent(model), tool list, system prompt
    tools_common.py   Carlos · shared tools + shared constants
    tools_plan.py     Carlos · plan + marketing tools
    tools_nego.py     Luca   · negotiation + diagnosis tools
    playbooks/
      core.md         Carlos · identity, strategy, global rules
      plan.md         Carlos
      marketing.md    Carlos
      negotiation.md  Luca
      diagnosis.md    Luca
  tests/
  scripts/merge.py    Carlos · builds the 2 files we paste into the Workspace
  build/              output of merge.py (tools.py + main.py for the Workspace)
```

## 3. How the files are joined (the merge)
The platform agent has exactly **two files**: `agents/<id>/main.py` and `agents/<id>/tools.py`. We assume extra modules can NOT be imported.
`scripts/merge.py` does:
1. `build/tools.py` = `tools_common.py` + `tools_nego.py` + `tools_plan.py`, concatenated **in that order**, with the duplicate import lines removed.
2. `build/main.py` = `agent/main.py` with the placeholder `{{SYSTEM_PROMPT}}` replaced by `core.md + negotiation.md + plan.md + marketing.md + diagnosis.md`, in that order.

Rules this imposes on every file:
- Allowed imports at the top of each tools file: `json, math, re, statistics, pathlib.Path, datetime`, `from studio import tool`, `from simulator import request`, and `pandas as pd` **only inside functions**. No other dependencies.
- Never import one tools file from another. Use the shared names from `tools_common.py` directly: after merging they sit in the same module. When testing locally, put `from tools_common import *` at the top of your file, inside a `# MERGE:STRIP` / `# MERGE:END` block that merge.py deletes.
- Each tools file ends with exactly one list: `COMMON_TOOLS = [...]`, `NEGO_TOOLS = [...]` or `PLAN_TOOLS = [...]`.

## 4. Naming rules (prevent collisions after concatenation)
| Kind | Carlos | Luca | Shared (tools_common) |
|---|---|---|---|
| @tool functions | `plan_*`, `mkt_*` | `nego_*`, `diag_*` | `get_company_state`, `read_invoke_summary`, `read_file_head`, `save_json_file` |
| private helpers | `_plan_*`, `_mkt_*` | `_nego_*`, `_diag_*` | `_common_*` |
| constants | `PLAN_*`, `MKT_*` | `NEGO_*`, `DIAG_*` | `APPROVED_SERVICES`, `FARE_BOUNDS`, `FLEET_TARGET`, `CHARGER_COST_EUR`, `CASH_FLOOR_EUR` |
| output files the agent writes | `output/plan_*.json`, `output/mkt_*.json` | `output/nego_*.json`, `output/diag_*.json` | — |
| playbook heading | `## TAREA: PLAN MENSUAL`, `## TAREA: MARKETING` | `## TAREA: NEGOCIACIÓN`, `## TAREA: DIAGNÓSTICO` | `# urbAIn · núcleo` |

Tool docstrings are in Spanish, start with a verb, and state WHEN to use the tool (the LLM chooses tools from the docstrings).

## 5. Shared tools (tools_common.py · owned by Carlos · already written)
| Name | Signature | Returns |
|---|---|---|
| `get_company_state` | `(section: str) -> dict` | `request(GET /api/v1/teams/{team_id}/company, section)`; sections: summary, strategy, assets, inventory, commitments, results |
| `read_invoke_summary` | `() -> str` | JSON: phase, calendar, month_in_phase, round, execution_limits, all `*_path` |
| `read_file_head` | `(path: str, max_chars: int = 6000) -> str` | text |
| `save_json_file` | `(name: str, content_json: str) -> str` | path written under `output/` |

## 6. Shared constants (single source; only Carlos edits)
```python
APPROVED_SERVICES = ["passenger_transport", "food_delivery"]
FARE_BOUNDS = {"base": (2.40, 4.80), "km": (0.85, 1.80)}
CHARGER_COST_EUR = 6000
CASH_FLOOR_EUR = 60000          # never commit below this cash level (variable costs + safety)
FLEET_TARGET = {                 # what negotiation buys toward; what the plan sizes chargers for
    "phase_1": {"bike": 24, "scooter": 10},   # ≈34 vehicles, delivered M1–M2 preferred
    "phase_2": {"bike": 34, "scooter": 12},   # cumulative target (revised after F1 results)
    "phase_3": {"bike": 40, "scooter": 12},
    "preferred_variants": {"bike": ["high_low", "high_medium", "medium_medium"],
                           "scooter": ["high_medium", "high_low", "medium_medium"]},
    "max_unit_price": {"bike": 1800, "scooter": 1450},
    "min_quality_pct": 95,
    "max_phase_spend_eur": 120000,   # vehicles only, cash basis (advance + balance)
}
```
These are starting values; Carlos's analysis may update them before the freeze. Luca reads `FLEET_TARGET` and must never hard-code his own copy.

## 7. The connection between the two tracks
There is no direct call between negotiation and the plan; they run as separate tasks. **The simulator state is the bridge**:
- Negotiation (Luca) → buys vehicles → the simulator records contracts, pending receipts and delivered assets.
- Plan (Carlos) → reads `get_company_state("assets")` and `("commitments")` → uses only vehicles that are received and active (`activation_month` ≤ current month; if absent, assume next month) → sizes chargers and zones.
- Both read `FLEET_TARGET` (intent) and `CASH_FLOOR_EUR` (limit).
- Optional breadcrumb: negotiation writes `output/nego_last_turn.json` = `{"phase", "round", "actions":[...], "accepted":[{"product_id","variant","qty","unit_price","delivery_schedule"}], "spent_commitment_eur"}`. Useful for traces and the pitch. The plan must NOT depend on it (output files may not persist between tasks).

## 8. Sync points
| When | What |
|---|---|
| T+0 | Both read CONTEXT.md + INTERFACE.md. Carlos creates the Python agent in the Workspace and shares the generated `main.py`/`tools.py` templates and the 4 schema files with Luca. |
| T+60 min | Each has a v0 with every tool returning valid output on fixtures; `pytest` passes. Carlos runs `scripts/merge.py` and pastes `build/*` into the Workspace → Playground runs: Luca's "Oferta de cinco bicicletas", Carlos's "Ensayo de la final · flota y mercado". |
| T+120 min | v1 improvements merged + critic pass + both Playground tests again. |
| Freeze (time decided at T+0) | Carlos pastes the final `build/*`, runs "Comprobar requisitos" → "Usar este agente en la competición". Nothing merges after this. |

## 9. Change requests
(Write here: date/time · who · what · why. Both must agree.)
- 2026-10-17 · Carlos · No shared constant changed. Analyst (analysis/fleet_scenarios.md) suggests a smaller FLEET_TARGET (F1 bike 16 / scooter 6; F2–F3 bike 22 / scooter 8, high-battery bikes). We keep the current FLEET_TARGET (34 in F1): a vehicle costs ≈25 €/month and the extra stock covers random peaks and the 15-min pickup promise. Luca: no action needed.
- 2026-10-17 · Carlos · Plan tools added (plan_prepare_context, plan_build, plan_build_maintenance, mkt_build_campaign). They write output/plan_context.json, output/plan_borrador.json, output/plan_validado.json, output/mkt_campaign.json (plan_*/mkt_* prefixes only).
