# Lleva: an LLM agent that runs a mobility-services company in a simulated market

Team **urbAIn**'s agent for the final of the **Gipuzkoa AI Hackathon** (Donostia, 17 October 2026). The final was a live, simulated market: each team's agent ran a shared-mobility services company in Donostia, buying vehicles from manufacturers, launching marketing, planning the monthly service and diagnosing fleet faults. A scoring function then ranked every company on profit, demand served, service quality and other factors.

Our agent, **Lleva**, ran on the organisers' agent platform (LangChain `create_agent` + platform `@tool`s). It talked to the simulator only through its REST API.

## What the agent does

| Platform task | Tools | Owner |
|---|---|---|
| Monthly **service plan** (prices, pooled vs. dedicated service, fleet per area, chargers, cash reserve) | `agent/tools_plan.py` | Carlos |
| **Marketing campaign** (channels, segments, budget within the €3,000 cap, or a reasoned opt-out) | `agent/tools_plan.py` | Carlos |
| Optional fleet **maintenance** before each month | `agent/tools_plan.py` | Carlos |
| **Negotiation** with vehicle manufacturers (quotes, offers, counter-offers over two rounds) | `agent/tools_nego.py` | Luca |
| **Fault diagnosis** of three asset alerts from a maintenance library | `agent/tools_nego.py` | Luca |
| Shared API helpers, constants and the system prompt | `agent/tools_common.py`, `agent/main.py`, `agent/playbooks/` | Carlos |

### Engineering highlights

- **Deterministic tools, LLM for orchestration.** The plan is built by code from live API state (cash, assets, commitments, demand) and checked against the platform's JSON schema and business rules (`_plan_business_errors`) before submission. The model decides *when* to call tools, not the numbers.
- **Stateless by design.** Each platform tool runs isolated and only API responses persist, so every compute tool re-reads the state it needs instead of relying on files from earlier calls.
- **Fleet sizing from data.** `analysis/fleet_analysis.py` turns 122 days of demand history (~260k trips) into per-area peak demand, vehicle cycle times and lean/base/aggressive scenarios (`analysis/fleet_scenarios.md`).
- **Two-person workflow.** Separate files per owner, a written interface contract (`docs/INTERFACE.md`), and `scripts/merge.py`, which merges both tracks into the two files the platform accepts (`build/main.py`, `build/tools.py`) and fails on any name collision.
- **Offline simulator.** `tests/platform_sim.py` replays the platform's task sequence (negotiation, marketing, monthly plans, maintenance) against captured API fixtures and asserts every schema and rule. The submitted build passed with `RESULT: ALL OK`.

## Repository layout

```
agent/            source, split by owner (tools_*.py + playbooks/*.md system-prompt sections)
build/            merged files submitted to the platform (main.py, tools.py)
scripts/merge.py  agent/ -> build/
tests/            platform_sim.py, test_plan.py and API fixtures captured from the Playground
analysis/         fleet sizing from demand history
docs/INTERFACE.md team contract: names, files, ownership
```

## Running

```bash
python scripts/merge.py        # rebuild build/ from agent/
python tests/platform_sim.py   # offline end-to-end check
```

The agent itself needs the organisers' platform (`studio`, `simulator`) and is not runnable outside it. `platform_sim.py` and `analysis/` also read the competition's market data (`data/mercado`, `data/maintenance_library`). That data was supplied to participants and is **not** included here.

## Stack

Python, LangChain agents, REST APIs, JSON Schema validation, pandas.

## Team

**urbAIn**: Carlos Tesoriero (service plan, marketing, integration) and Luca (negotiation, diagnosis). The same team also built [flAIre](https://github.com/ctesorierog/flaire-wildfire-access-agent), a top-3 project in the hackathon's first phase.
