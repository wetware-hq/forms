#!/usr/bin/env python3
"""Exit 1 if (a) a RULES.md row names no existing test, or (b) code outside messages.py holds
prose string literals (user-facing text must come from messages.LINES), or (c) msg() uses an
id that is not in the wording table. Exit 0 otherwise."""
import ast, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import messages


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
                    and isinstance(n.args[0], ast.Constant) and n.args[0].value not in messages.LINES:
                out.append(f"{p.name}:{n.lineno}: msg id {n.args[0].value!r} not in wording table")
    return out


def main():
    reg, lit = register_problems(), literal_problems()
    for x in reg:
        print("REGISTER", x)
    for x in lit:
        print("WORDING", x)
    print(f"rulecheck: {len(reg)} register rows without tests, {len(lit)} wording violations")
    return 1 if reg or lit else 0


if __name__ == "__main__":
    sys.exit(main())
