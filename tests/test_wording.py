import pytest
"""WORDING.md is the only wording source in code; expected values in these checks come from the signed file."""
import ast, hashlib, pathlib, re
import messages
from signed_source import signed_rows as _signed_rows, signed_text as _signed_text

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEXT = (ROOT / "WORDING.md").read_text()


def test_wording_matches_its_header_hash():
    head, body = TEXT.split("\n\n", 1)
    assert re.search(r"^sha256: ([0-9a-f]{64})$", head, re.M).group(1) == hashlib.sha256(body.encode()).hexdigest()
    assert messages.SHA256 == hashlib.sha256(body.encode()).hexdigest()
    assert messages.LINES == _signed_rows()


def test_any_edit_breaks_the_hash():
    head, body = TEXT.split("\n\n", 1)
    assert hashlib.sha256(body.replace("You answered", "You answerd", 1).encode()).hexdigest() != messages.SHA256


def used_ids():
    ids = set()
    for p in list(ROOT.glob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "msg" and n.args and isinstance(n.args[0], ast.Constant):
                ids.add(n.args[0].value)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and re.fullmatch(r"[A-Z]{2,4}-[A-Z0-9-]+", n.value):
                ids.add(n.value)
    return ids


def test_every_line_id_used_in_code_exists_in_the_copy():
    missing = sorted(i for i in used_ids() if i not in messages.LINES and i not in messages.PENDING)
    assert not missing, missing


def test_messages_py_holds_no_wording():
    tree = ast.parse((ROOT / "messages.py").read_text())
    texts = set(_signed_rows().values()) | set(messages.PENDING.values())
    consts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [c for c in consts if " " in c and (c in texts or any(len(t) > 12 and t in c for t in texts))]


def test_pending_lines_are_not_signed():
    assert set(messages.PENDING) == set()
    assert not set(messages.PENDING) & set(_signed_rows())


def test_signed_lists_loaded():
    signed = _signed_rows()
    assert list(messages.SAMEDAY_STATUS) == ["unconfirmed", "confirmed", "changed", "declined", "unknown"]
    assert all(messages.SAMEDAY_STATUS[k] == signed[f"ST-{k.upper()}"] for k in messages.SAMEDAY_STATUS)
    assert set(messages.RELATIONSHIP) == {"parent", "guardian", "sdm"} and len(messages.LINES) == len(signed)
    assert all(messages.RELATIONSHIP[r] == (signed[f"REL-{r.upper()}-PT"], signed[f"REL-{r.upper()}-CLIN"]) for r in messages.RELATIONSHIP)


def test_waiting_parent_line_adds_no_full_stop():
    line = messages.msg("CQ-WAITING-PARENT", n=1, parent_text="Any allergy?", m=2, text="Was it severe?")
    assert line == "Waiting on Q1: Any allergy? Then ask Q2: Was it severe?" and "?." not in line
    for k, v in messages.LINES.items():
        assert "?." not in v, k


def test_rulecheck_reports_pending_without_failing(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("rulecheck", ROOT / "scripts" / "rulecheck.py")
    rc = importlib.util.module_from_spec(spec); spec.loader.exec_module(rc)
    monkeypatch.setattr(messages, "PENDING", {"BK-SYNTH-DRAFT": "Draft line."})
    assert rc.pending_report() == (["BK-SYNTH-DRAFT"], [])
    monkeypatch.setattr(messages, "PENDING", {"PV-OPEN": "Not answered yet"})
    assert rc.pending_report()[1]


def test_sync_render_is_deterministic_and_drops_signed_pending(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_wording", ROOT / "scripts" / "sync_wording.py")
    sw = importlib.util.module_from_spec(spec); spec.loader.exec_module(sw)
    signed = "# x\n| id | line |\n|---|---|\n| PV-OPEN | Not answered yet |\n| ST-CONFIRMED | confirmed |\n" \
             "| LT-X | clinician | x | Not a two-column row. |\n"
    out = sw.render(signed, [("RF-NEW", "Draft.")])
    assert out == sw.render(signed, [("RF-NEW", "Draft.")])
    assert "| PV-OPEN | Not answered yet |" in out and "| LT-X | Not a two-column row. |" in out and "| ST-CONFIRMED | confirmed |" in out and "| RF-NEW | Draft. | pending |" in out
    real = sw.render(_signed_text())
    assert all(f"| {k} | {v} |" in real for k, v in _signed_rows().items())
    head, body = out.split("\n\n", 1)
    assert head.endswith(__import__("hashlib").sha256(body.encode()).hexdigest())


def test_every_status_and_relationship_resolves_to_a_row():
    for k, v in messages.SAMEDAY_STATUS.items():
        assert messages.LINES[f"ST-{k.upper()}"] == v
    for role, (pt, clin) in messages.RELATIONSHIP.items():
        assert messages.LINES[f"REL-{role.upper()}-PT"] == pt and messages.LINES[f"REL-{role.upper()}-CLIN"] == clin
    src = (ROOT / "messages.py").read_text()
    for k in ("unconfirmed", "confirmed", "changed", "declined", "unknown"):
        assert f"ST-{k.upper()}" in messages.LINES
    assert "## Relationship roles" not in TEXT and "## Queue statuses" not in TEXT


def test_sync_keeps_every_signed_row_and_refuses_short_copies():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync", ROOT / "scripts" / "sync_wording.py")
    s = importlib.util.module_from_spec(spec); spec.loader.exec_module(s)
    signed = "| PV-A | one |\n| LT-B | patient | x | two |\n"
    out = s.render(signed)
    assert "| PV-A | one |" in out and "| LT-B | two |" in out
    with pytest.raises(SystemExit):
        s.verify(signed, "| PV-A | one |\n")
    with pytest.raises(SystemExit):
        s.verify(signed, "| PV-A | one |\n| LT-C | two |\n")
    with pytest.raises(SystemExit):
        s.verify(signed, "| PV-A | one |\n| PV-A | one |\n")
    s.verify(_signed_text(), TEXT.split("\n\n", 1)[1])


def test_wording_has_every_signed_row():
    import re
    body = TEXT.split("\n\n", 1)[1].split("## Pending signature")[0]
    rows = re.findall(r"^\| ([A-Z]{2,4}-[A-Z0-9-]+) \|", body, re.M)
    assert len(rows) == len(set(rows)) and set(rows) == set(_signed_rows())
