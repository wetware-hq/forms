#!/usr/bin/env python3
"""Exit 1 if (a) a RULES.md row names no existing test, or (b) code outside messages.py holds
prose string literals (user-facing text must come from messages.LINES), or (c) msg() uses an
id that is not in the signed wording table, or (d) a messages.LINES entry or a RULES.md W- row
differs from the signed table WORDING.md. WORDING.md is the only wording source. Exit 0 otherwise."""
import ast, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import messages


def signed_table():
    rows = re.findall(r"^\| ([A-Z]{2}-[A-Z0-9-]+) \| (.*) \|$", (ROOT / "WORDING.md").read_text(), re.M)
    return dict(rows)


SIGNED = signed_table()


def pending_report():
    """Lines in messages.PENDING (not in the signed table): reported, never a failure. WORDING.md stays the only
    wording source rulecheck reads; tests/test_wording.py checks PENDING against the vendored draft."""
    out, bad = [], []
    for k, v in messages.PENDING.items():
        if k in SIGNED:
            bad.append(f"messages.py: {k} is signed now; move it into LINES")
        else:
            out.append(k)
    return out, bad


def signed_problems():
    out = [f"messages.py: {k} not word for word as signed" for k, v in messages.LINES.items() if SIGNED.get(k) != v]
    for line in (ROOT / "RULES.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 6 and cells[0].startswith("W-"):
            k = cells[0][2:]
            if k in messages.PENDING and k not in SIGNED:
                if cells[1] != messages.PENDING[k] or "pending signature" not in cells[2]:
                    out.append(f"RULES.md: {cells[0]} must match the draft and be marked pending signature")
                continue
            if SIGNED.get(k) != cells[1]:
                out.append(f"RULES.md: {cells[0]} not word for word as signed")
            if "signed" not in cells[2] or "unsigned" in cells[2]:
                out.append(f"RULES.md: {cells[0]} not marked signed")
    return out


def tests_defined():
    names = set()
    for p in (ROOT / "tests").glob("test_*.py"):
        names |= set(re.findall(r"^def (test_\w+)", p.read_text(), re.M))
    return names


def register_problems():
    have, out = tests_defined(), []
    for line in (ROOT / "RULES.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 6 or not re.match(r"^[A-Z]+-[\w-]+$", cells[0]):
            continue
        tests = re.findall(r"test_\w+", cells[5])
        missing = [t for t in tests if t not in have]
        if not tests or missing:
            out.append(f"{cells[0]}: " + ("no test" if not tests else "missing " + ", ".join(missing))
                       + (f" [{cells[2]}]" if cells[2] else ""))
    return out


def literal_problems():
    out = []
    for p in sorted(ROOT.glob("*.py")):
        if p.name == "messages.py":
            continue
        tree = ast.parse(p.read_text())
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs \
                    and re.search(r"[A-Za-z]+ [A-Za-z]+", n.value):
                out.append(f"{p.name}:{n.lineno}: prose literal {n.value[:40]!r}")
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "msg" and n.args \
                    and isinstance(n.args[0], ast.Constant) and n.args[0].value not in SIGNED and n.args[0].value not in messages.PENDING:
                out.append(f"{p.name}:{n.lineno}: msg id {n.args[0].value!r} not in wording table")
    return out


def main():
    pend, pbad = pending_report()
    reg, lit = register_problems(), literal_problems() + signed_problems() + pbad
    for x in pend:
        print("PENDING", x, "awaiting signature (not a failure)")
    for x in reg:
        print("REGISTER", x)
    for x in lit:
        print("WORDING", x)
    print(f"rulecheck: {len(reg)} register rows without tests, {len(lit)} wording violations, {len(pend)} lines pending signature")
    return 1 if reg or lit else 0


if __name__ == "__main__":
    sys.exit(main())
