"""Static check: every refusal code the gate or step can raise, read from the source with ast (not a sweep).
Each code a patient session can reach must map to a signed PV line in PATIENT_LINE; an unmapped code fails."""
import ast, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import forms as M
import messages

# Codes raised only for an action the patient role may not take (the permissions check refuses first).
NOT_PATIENT = {"already_approved": "approve", "nothing_to_review": "review", "nothing_to_close": "close_sameday", "status_not_on_signed_list": "close_sameday"}
# Codes raised only inside an `if s.role == "clinician" ...` branch (checked below by ast): no patient session reaches them.
CLINICIAN_ONLY = {"decline_override_needs_reason"}
SESSION_PATHS = ("_gate", "step", "call", "observe", "_refuse")


def raised_codes(src):
    out = set()
    for f in ast.walk(ast.parse(src)):
        if isinstance(f, ast.FunctionDef) and f.name in SESSION_PATHS:
            for n in ast.walk(f):
                if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "code" and n.args:
                    a = n.args[0]
                    if isinstance(a, ast.Constant):
                        out.add(a.value)
                    elif isinstance(a, ast.BinOp) and isinstance(a.left, ast.Constant) and a.left.value == "role_":
                        out |= {"role_" + t for t in M.FIELDS if t not in M.PERMS["patient"]}
                    else:
                        out.add("<dynamic:" + ast.unparse(a) + ">")
    return out


def unmapped(codes, table):
    return sorted(c for c in codes if c not in NOT_PATIENT and c not in CLINICIAN_ONLY and not (c in table and table[c].startswith("PV-")
                                                                    and table[c] in messages.LINES))


def test_not_patient_codes_really_need_a_role_the_patient_lacks():
    for c, action in NOT_PATIENT.items():
        assert action not in M.PERMS["patient"], c


def test_every_patient_reachable_code_has_a_signed_pv_line():
    codes = raised_codes((ROOT / "forms.py").read_text())
    assert "role_fixed_at_session_open" in codes and len(codes) > 5
    assert unmapped(codes, M.PATIENT_LINE) == []


def test_static_check_fails_on_an_unmapped_code():
    codes = raised_codes((ROOT / "forms.py").read_text())
    for c in M.PATIENT_LINE:
        t = dict(M.PATIENT_LINE); del t[c]
        assert c in unmapped(codes | {c}, t)
    assert unmapped({"made_up_code"}, M.PATIENT_LINE) == ["made_up_code"]
    assert unmapped({"x"}, {"x": "RF-NOT-YOURS"}) == ["x"] and unmapped({"x"}, {"x": "PV-NO-SUCH"}) == ["x"]


def test_clinician_only_codes_sit_under_a_clinician_role_check():
    tree = ast.parse((ROOT / "forms.py").read_text())
    for c in CLINICIAN_ONLY:
        guarded = [n for n in ast.walk(tree) if isinstance(n, ast.If) and "s.role == 'clinician'" in ast.unparse(n.test)
                   and any(isinstance(x, ast.Call) and getattr(x.func, "id", None) == "code" and x.args
                           and getattr(x.args[0], "value", None) == c for b in n.body for x in ast.walk(b))]
        assert guarded, c
