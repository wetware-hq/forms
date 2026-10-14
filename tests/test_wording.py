"""Every patient-view line in messages.py matches the signed wording table (WORDING.md) word for word."""
import pathlib, re
import messages

ROOT = pathlib.Path(__file__).resolve().parent.parent
SIGNED = dict(re.findall(r"^\| ([A-Z]{2}-[A-Z0-9-]+) \| (.*) \|$", (ROOT / "WORDING.md").read_text(), re.M))


def test_signed_table_has_51_lines():
    assert len(SIGNED) == 51


def test_patient_view_lines_match_signed_table():
    pv = {k: v for k, v in messages.LINES.items() if k.startswith("PV-")}
    assert pv and set(k for k in SIGNED if k.startswith("PV-")) <= set(pv)
    for k, v in pv.items():
        assert v == SIGNED[k], k


def test_relationship_patient_words_match_signed_table():
    text = (ROOT / "WORDING.md").read_text()
    for rid, (patient, clinician) in messages.RELATIONSHIP.items():
        assert f"| {rid} | {patient} | {clinician} |" in text
