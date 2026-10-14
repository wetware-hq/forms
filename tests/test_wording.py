"""Every patient-view line in messages.py matches the signed wording table (WORDING.md) word for word."""
import pathlib, re
import messages

ROOT = pathlib.Path(__file__).resolve().parent.parent
SIGNED = dict(re.findall(r"^\| ([A-Z]{2}-[A-Z0-9-]+) \| (.*) \|$", (ROOT / "WORDING.md").read_text(), re.M))


def test_signed_table_has_58_lines():
    assert len(SIGNED) == 58


def test_patient_view_lines_match_signed_table():
    pv = {k: v for k, v in messages.LINES.items() if k.startswith("PV-")}
    assert pv and set(k for k in SIGNED if k.startswith("PV-")) <= set(pv)
    for k, v in pv.items():
        assert v == SIGNED[k], k


def test_relationship_patient_words_match_signed_table():
    text = (ROOT / "WORDING.md").read_text()
    for rid, (patient, clinician) in messages.RELATIONSHIP.items():
        assert f"| {rid} | {patient} | {clinician} |" in text


def test_round5_lines_signed_and_used_word_for_word():
    r5 = ("RF-HARNESS-ONLY", "RF-NOT-YOURS", "RF-EXPORT-REAL", "ST-CHECK-PASS", "ST-CHECK-FAIL", "CQ-THREE-FAILS", "RF-WAIT-CLINICIAN")
    assert all(messages.LINES[k] == SIGNED[k] for k in r5)
    assert not set(messages.PENDING) & set(SIGNED)


def test_rulecheck_reports_pending_without_failing(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("rulecheck", ROOT / "scripts" / "rulecheck.py")
    rc = importlib.util.module_from_spec(spec); spec.loader.exec_module(rc)
    monkeypatch.setattr(messages, "PENDING", {"BK-SYNTH-DRAFT": "Draft line."})
    assert rc.pending_report() == (["BK-SYNTH-DRAFT"], [])
    monkeypatch.setattr(messages, "PENDING", {"PV-OPEN": "Not answered yet"})
    assert rc.pending_report()[1]
