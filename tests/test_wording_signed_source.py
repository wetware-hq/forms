"""Every line in WORDING.md is an exact copy of its row in the signed source file (no skip: a missing signed file
fails). The signed file is found through STACK_SIBLINGS_DIR or the directory holding this checkout."""
import os, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE if (HERE / "WORDING.md").is_file() else HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sync_wording


def test_every_wording_line_matches_signed_source():
    sib = pathlib.Path(os.environ.get("STACK_SIBLINGS_DIR") or ROOT.parent)
    signed = dict(sync_wording.signed_rows((sib / "wording" / "forms_orders_lines_SIGNED.md").read_text()))
    body = (ROOT / "WORDING.md").read_text().split("## Pending signature")[0]
    have = dict(sync_wording.ROW.findall(body))
    assert have and have == signed
