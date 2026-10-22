# Fleet scenarios (F1, pax + food, our 6 areas)
Source: `analysis/fleet_analysis.py`. History = 122 days (2026-03-06..07-05, 17.4 weeks, 260k rows; 14,918/week, which matches CONTEXT §5).
Demand = per-day average ×1.4 (F1). Pax+food origins in our 6 areas = **2,545 req/day** (Centro 1,134 · Gros 524 · Amara 300 · Antiguo 299 · Aiete 147 · Altza 141).
Peak hour per area (pax+food, req/h): Centro 116 @21h · Amara 56 @7h · Gros 53 @21h · Altza 40 @8h · Antiguo 35 @18h · Aiete 24 @8h.

Cycle = 6 min pickup + observed trip (experiencias, by origin area) + 5 min reposition + recharge allowance
(bike high_low: 0.83 %/km, 96 km per 20->100 % charge, 66.7 min; +1 km empty per trip). Cycle: Gros 16.0 · Centro 16.6 · Antiguo 17.1 · Amara 18.6 · Aiete 19.2 · Altza 22.1 min.
Avg trip km: Gros 1.26 · Centro 1.41 · Antiguo 1.68 · Amara 2.28 · Aiete 2.53 · Altza 3.56.

| Scenario | share | served/day | score pts (ref 186) | veh (min, peak) | chargers | margin/mo | depr./mo | profit/mo |
|---|---|---|---|---|---|---|---|---|
| lean | 5 % | 127 | 40.6 | 7 | 6 | 6.7 k€ | 0.7 k€ | **6.1 k€** |
| base | 8 % | 204 | 52.3 | 11 | 6 | 10.8 k€ | 0.8 k€ | **10.0 k€** |
| aggressive | 12 % | 305 | 62.1 | 14 | 6 | 16.1 k€ | 0.9 k€ | **15.3 k€** |

Minimum vehicles per area (peak req/h × cycle/60, rounded up):
| Area | lean | base | aggr | charger-h/day (base) |
|---|---|---|---|---|
| Centro | 2 | 3 | 4 | 2.5 |
| Gros | 1 | 2 | 2 | 1.1 |
| Amara | 1 | 2 | 3 | 0.9 |
| Antiguo | 1 | 1 | 2 | 0.7 |
| Altza | 1 | 2 | 2 | 0.6 |
| Aiete | 1 | 1 | 1 | 0.5 |
Chargers = max(1, ceil(v/20)) = 1 per area in every scenario (6 total). Charger load is ≤ 4 h/day, so 1 charger is enough for capacity.

Notes on the economics
- Margin per trip at 2.95/0.98 (pax) is about 1.6–2.4 €. Energy is about 0.003 €/km (negligible). Month = 28 days.
- Depreciation is small: a vehicle costs about 25 €/mo (1500/60) and a charger about 83 €/mo (6000/72). **The binding limit is the share of demand we win, not fleet cost.**
- The peak-hour formula is a floor. Poisson arrivals, a 15-min pickup promise, fleet sitting in the wrong cell, recharge pile-ups and the pooled 7–8 h commute plus 21 h food peak all argue for a **×1.7–2 buffer**. Availability also feeds engine choice and the quality score.

## Recommendation
- FLEET_TARGET (vehicles active per phase):
  F1 `{"bike": 16, "scooter": 6}` (22, about 2× the base minimum and enough for the aggressive scenario with buffer).
  F2 `{"bike": 22, "scooter": 8}` (30). F3 `{"bike": 22, "scooter": 8}` (hold; grow only if served/day > 250).
  Bikes high battery (Altza/Aiete/Amara longer trips, Gros->campus corridor). Scooters for short Centro/Gros trips.
- Area weights: `{"Centro + Parte Vieja": 0.28, "Gros + Zurriola + Ategorrieta": 0.22, "Antiguo + Ondarreta + Ibaeta": 0.18, "Amara + Egia + Loiola + Riberas": 0.12, "Altza + Intxaurrondo + Bidebieta + Herrera": 0.10, "Aiete": 0.10}`.
  Why: Centro is 45 % of demand but has the shortest cycle. Gros (homes) and Antiguo (campus, 34 % of young demand) carry the student corridor. Altza has long 22-min cycles and the worst T−1 service (29 % unserved), which helps the equity score. Aiete is ≥ 7 %.
- Chargers (base): 1 per area = 6 in M1. Add the 7th and 8th in Gros and Antiguo (student anchors) when fleet ≥ 25, and a 2nd in Amara if anchors are single cells (see below).
- Fares: T−1 traditional fit = pax 3.16 + 1.07/km, food 3.11 + 1.02/km (avg pax 5.19 €, food 4.62 €). **Keep 2.95/0.98 pax and 2.90/0.95 food**: that is about 7–8 % under traditional with a healthy margin. Do not go lower.

## Single H3 cell as fleet anchor?
Share of each area's pax+food origins within 1 km (1.5 km) of the area's top origin cell:
Centro 99 % (100) · Gros 87 % (95) · Aiete 79 % (100) · Antiguo 71 % (93) · Altza 52 % (86) · **Amara 37 % (67)**.
The top cell alone holds only 2–11 % of origins, but the radius is what matters for a 6-min pickup at about 25 km/h (≈2.5 km).
Verdict: a single anchor is reasonable for Centro, Gros, Aiete and Antiguo. It is acceptable for Altza. **Amara is weak, so use 2 anchors** (or a central Amara/Egia cell). For Antiguo, prefer the campus cell `8a184bb36a57fff` over the top-origin cell `8a184bb36a37fff` (it is nearby).
Top origin cells: Centro 8a184bb34147fff · Gros 8a184bb34847fff · Amara 8a184bb34baffff · Antiguo 8a184bb36a37fff · Altza 8a184bb26d2ffff · Aiete 8a184bb3081ffff.
