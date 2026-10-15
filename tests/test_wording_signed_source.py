"""Every line in WORDING.md is an exact copy of its row in the signed source file (no skip: a missing signed file
fails). The signed file is found through STACK_SIBLINGS_DIR or the directory holding this checkout."""
import os, pathlib, sys
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE if (HERE / "WORDING.md").is_file() else HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sync_wording

# Committed row count of forms_orders_lines_SIGNED.md (room ruling 09:51). Changed in the same commit as the signed
# file changes: the test compares the count read off the file with this number.
SIGNED_ROW_COUNT = 128


def test_every_wording_line_matches_signed_source():
    sib = pathlib.Path(os.environ.get("STACK_SIBLINGS_DIR") or ROOT.parent)
    raw = (sib / "wording" / "forms_orders_lines_SIGNED.md").read_bytes().decode("utf-8")
    # byte-exact: the wording cell is taken raw (one pad space each side, nothing else stripped)
    cells = {k: rest.rstrip("\r").split("|")[-2] if rest.rstrip().endswith("|") else rest.split("|")[-1]
             for k, rest in __import__("re").findall(r"^\| ([A-Z]{2,4}-[A-Z0-9-]+) \|(.*)$", raw, __import__("re").M)}
    assert all(c.startswith(" ") and c.endswith(" ") for c in cells.values()), "signed cell padding is not one space"
    signed = {k: c[1:-1] for k, c in cells.items()}
    body = (ROOT / "WORDING.md").read_text().split("## Pending signature")[0]
    have = dict(__import__("re").findall(r"^\| ([A-Z]{2,4}-[A-Z0-9-]+) \| (.*) \|$", body, __import__("re").M))
    assert len(signed) == SIGNED_ROW_COUNT, f"signed file has {len(signed)} rows, committed count is {SIGNED_ROW_COUNT}"
    assert have and have == signed
