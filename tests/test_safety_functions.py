"""Every function that raises a refusal, maps a line, opens a queue entry or writes the session/log must be listed
in safety_functions.toml, which is the only input to scripts/mutate.py. Found by an AST scan, not by hand."""
import ast, pathlib, tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = tomllib.loads((ROOT / "safety_functions.toml").read_text())
CALLS = {"code", "msg", "_refuse", "Invalid", "Refused"}
LINE_TABLES = {"PATIENT_LINE", "ROUTES", "SD", "SAMEDAY_STATUS", "RELATIONSHIP", "DENY"}
QUEUE_VARS = {"sd", "sdm"}           # local names for the queue-entry dict passed into helpers
STATE = {"session", "log", "sameday", "grants", "done", "cancelled", "names", "access", "patient", "results",
         "interpreter", "fails", "passed", "missing", "submissions"}


def _writes_state(n):
    tg = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, (ast.AugAssign, ast.AnnAssign)) else []
    for t in tg:
        for x in ast.walk(t):
            if isinstance(x, ast.Attribute) and x.attr in STATE:
                return True
            if isinstance(x, ast.Subscript) and isinstance(x.slice, ast.Constant) and x.slice.value in STATE:
                return True
            if isinstance(x, ast.Subscript) and isinstance(x.value, ast.Name) and x.value.id in QUEUE_VARS:
                return True
    return isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("append", "pop", "add", "update", "clear") \
        and isinstance(n.func.value, (ast.Attribute, ast.Subscript, ast.Name)) and any(
            (isinstance(x, ast.Attribute) and x.attr in STATE) or (isinstance(x, ast.Subscript) and isinstance(x.slice, ast.Constant) and x.slice.value in STATE)
            for x in ast.walk(n.func.value))


def is_safety(f):
    for n in ast.walk(f):
        if isinstance(n, ast.Raise):
            return True
        if isinstance(n, ast.Call) and (getattr(n.func, "id", None) in CALLS or getattr(n.func, "attr", None) in CALLS):
            return True
        if isinstance(n, ast.Name) and n.id in LINE_TABLES:
            return True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith(("CQ-", "RF-", "PV-")):
            return True
        if _writes_state(n):
            return True
    return False


def scan(src):
    return sorted({f.name for f in ast.walk(ast.parse(src)) if isinstance(f, ast.FunctionDef) and is_safety(f)})


def missing(src, listed):
    return [f for f in scan(src) if f not in listed]


def test_every_safety_function_is_listed():
    assert missing((ROOT / CFG["module"]).read_text(), set(CFG["functions"])) == []


def test_listed_functions_exist():
    names = {f.name for f in ast.walk(ast.parse((ROOT / CFG["module"]).read_text())) if isinstance(f, ast.FunctionDef)}
    assert sorted(set(CFG["functions"]) - names) == []


def test_scan_catches_a_planted_omission():
    src = (ROOT / CFG["module"]).read_text()
    for f in ("_gate", "_refuse", "step"):
        assert missing(src, set(CFG["functions"]) - {f}) == [f]
