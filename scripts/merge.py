"""merge.py · OWNER: Carlos · builds build/tools.py and build/main.py for the Workspace."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
A = ROOT / "agent"
OUT = ROOT / "build"
OUT.mkdir(exist_ok=True)

IMPORT_RE = re.compile(r"^(import \w+|from [\w.]+ import [\w, ]+)\s*$")


def strip(src):
    src = re.sub(r"# MERGE:STRIP.*?# MERGE:END\n", "", src, flags=re.S)
    return src


parts, imports = [], []
for name in ("tools_common.py", "tools_nego.py", "tools_plan.py"):
    body = []
    for line in strip((A / name).read_text(encoding="utf-8")).splitlines():
        if IMPORT_RE.match(line):
            if line not in imports:
                imports.append(line)
        else:
            body.append(line)
    parts.append(f"# ===== {name} =====\n" + "\n".join(body).strip() + "\n")

tools_py = "\n".join(imports) + "\n\n" + "\n\n".join(parts)
names = re.findall(r"^def (\w+)\(", tools_py, flags=re.M) + re.findall(r"^([A-Z_]+)\s*=", tools_py, flags=re.M)
dupes = sorted({n for n in names if names.count(n) > 1})
if dupes:
    raise SystemExit(f"Name collision after merge: {dupes} (see INTERFACE.md §4)")
compile(tools_py, "tools.py", "exec")  # fail before writing a broken build
(OUT / "tools.py").write_text(tools_py, encoding="utf-8")

order = ["core.md", "negotiation.md", "plan.md", "marketing.md", "diagnosis.md"]
prompt = "\n\n".join((A / "playbooks" / f).read_text(encoding="utf-8").strip() for f in order)
main = (A / "main.py").read_text(encoding="utf-8").replace("{{SYSTEM_PROMPT}}", prompt.replace('"""', "'''"))
compile(main, "main.py", "exec")
(OUT / "main.py").write_text(main, encoding="utf-8")
print("OK -> build/tools.py, build/main.py")
