# tools_common.py · OWNER: Carlos · shared tools + constants (see INTERFACE.md §5–6)
import json
import math
from pathlib import Path

from studio import tool
from simulator import request

APPROVED_SERVICES = ["passenger_transport", "food_delivery"]
FARE_BOUNDS = {"base": (2.40, 4.80), "km": (0.85, 1.80)}
CHARGER_COST_EUR = 6000
CASH_FLOOR_EUR = 60000
FLEET_TARGET = {
    "phase_1": {"bike": 24, "scooter": 10},
    "phase_2": {"bike": 34, "scooter": 12},
    "phase_3": {"bike": 40, "scooter": 12},
    "preferred_variants": {"bike": ["high_low", "high_medium", "medium_medium"],
                           "scooter": ["high_medium", "high_low", "medium_medium"]},
    "max_unit_price": {"bike": 1800, "scooter": 1450},
    "min_quality_pct": 85,   # catalogs publish ~85 %; the catalog target is used as floor
    "max_phase_spend_eur": 120000,
}


def _common_read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _common_schema_errors(schema, value, root=None, path="$", depth=0):
    """Validador JSON Schema mínimo (type, enum, const, required, additionalProperties, min/max,
    minItems/maxItems, minLength/maxLength, $ref, anyOf, allOf con if/then). Devuelve lista de errores."""
    root = schema if root is None else root
    if depth > 40 or not isinstance(schema, dict):
        return []
    errs = []
    if "$ref" in schema:
        ref = schema["$ref"]
        node = root
        for part in ref.lstrip("#/").split("/"):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        return _common_schema_errors(node, value, root, path, depth + 1)
    if "anyOf" in schema:
        opts = [_common_schema_errors(s, value, root, path, depth + 1) for s in schema["anyOf"]]
        if all(opts):
            errs.append(f"{path}: no cumple ninguna opción ({opts[0][:1]})")
    for sub in schema.get("allOf", []):
        if "if" in sub:
            if not _common_schema_errors(sub["if"], value, root, path, depth + 1) and "then" in sub:
                errs += _common_schema_errors(sub["then"], value, root, path, depth + 1)
        else:
            errs += _common_schema_errors(sub, value, root, path, depth + 1)
    if "const" in schema and value != schema["const"]:
        errs.append(f"{path}: debe ser {schema['const']}")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: valor {value!r} no permitido")
    typ = schema.get("type")
    checks = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
              "string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
              "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
              "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
              "null": lambda v: v is None}
    if typ and typ in checks and not checks[typ](value):
        return errs + [f"{path}: tipo {type(value).__name__}, se esperaba {typ}"]
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{path}.{k}: obligatorio")
        for k, v in value.items():
            if k in props:
                errs += _common_schema_errors(props[k], v, root, f"{path}.{k}", depth + 1)
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}.{k}: campo no admitido")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errs.append(f"{path}: mínimo {schema['minItems']} elementos")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: máximo {schema['maxItems']} elementos")
        if isinstance(schema.get("items"), dict):
            for i, v in enumerate(value):
                errs += _common_schema_errors(schema["items"], v, root, f"{path}[{i}]", depth + 1)
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errs.append(f"{path}: texto demasiado corto")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path}: texto demasiado largo ({len(value)}>{schema['maxLength']})")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: menor que {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: mayor que {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errs.append(f"{path}: debe ser > {schema['exclusiveMinimum']}")
    return errs


def _common_schema_file_errors(schema_paths, value):
    """Valida contra el primer esquema físico que exista. Si no hay ninguno, no bloquea (lista vacía)."""
    for sp in schema_paths:
        q = Path(sp)
        if q.is_file():
            try:
                return _common_schema_errors(json.loads(q.read_text(encoding="utf-8-sig")), value)
            except (OSError, ValueError):
                return []
    return []


@tool
def get_company_state(section: str) -> dict:
    """Consulta el estado propio de la empresa. section: summary, strategy, assets, inventory, commitments o results. Úsala antes de decidir."""
    return request("GET", "/api/v1/teams/{team_id}/company", params={"section": section})


COMMON_RUNTIME_FILES = [
    "sources/service_plan.schema.json", "referencia/contratos_api/negotiation.schema.json",
    "referencia/contratos_api/service_maintenance.schema.json", "mercado/zonas.csv",
    "mercado/historico_demanda.csv.gz", "referencia/vehiculos_servicios.csv", "referencia/recarga.csv",
    "referencia/costes.csv", "operaciones/condiciones_compra.json", "marketing/reference/channels.csv",
    "marketing/reference/segments.csv", "marketing/reference/campaign.schema.json",
    "mantenimiento/aviso.json", "mantenimiento/mediciones.csv", "mantenimiento/diagnostico.schema.json"]


def _common_api_docs(limit=40):
    """Respuestas completas de las APIs ya llamadas en esta ejecución (Studio las guarda en output/api/*.json)."""
    out = []
    root = Path("output/api")
    if not root.is_dir():
        return out
    files = sorted(root.glob("*.json"), key=lambda q: q.stat().st_mtime)[-limit:]
    for q in files:
        try:
            out.append(json.loads(q.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError):
            continue
    return out


@tool
def read_invoke_summary() -> str:
    """Resume el encargo: rutas de invoke si existen y, si no (contrato actual), los archivos disponibles del workspace. La fase, ronda y mes vienen en TASK_REQUEST; el estado se lee con get_company_state."""
    for p in ("input/invoke.json", "runtime/invoke.json"):
        if Path(p).exists():
            inv = _common_read_json(p)
            keep = {k: v for k, v in inv.items()
                    if k.endswith("_path") or k in ("phase", "calendar", "task", "month_in_phase",
                                                    "round", "execution_limits")}
            return json.dumps(keep, ensure_ascii=False)[:15000]
    return json.dumps({"invoke": "no disponible (normal en este contrato)",
                       "instruction": "Lee fase/ronda/mes en TASK_REQUEST y el estado con get_company_state; las herramientas plan_*/nego_* leen solas las respuestas guardadas.",
                       "available_files": [f for f in COMMON_RUNTIME_FILES if Path(f).exists()]}, ensure_ascii=False)


@tool
def read_file_head(path: str, max_chars: int = 6000) -> str:
    """Lee el principio de un archivo del workspace (md, json, csv). Úsala para consultar guías, esquemas o cabeceras."""
    p = Path(path)
    if not p.exists():
        return f"no existe: {path}"
    return p.read_text(encoding="utf-8", errors="replace")[:max_chars]


@tool
def save_json_file(name: str, content_json: str) -> str:
    """Guarda un objeto JSON en output/<name> y devuelve la ruta. Úsala para borradores y registros."""
    out = Path("output")
    out.mkdir(exist_ok=True)
    path = out / name
    path.write_text(json.dumps(json.loads(content_json), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


COMMON_TOOLS = [get_company_state, read_invoke_summary, read_file_head]
