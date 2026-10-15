#!/usr/bin/env python3
"""Mutation testing of every safety function listed in safety_functions.toml (no hand-picked list).
For each mutant: flip a comparison, swap and/or, drop a 'not', flip a True/False, remove a guard return,
remove one action from the permission table, map a PATIENT_LINE code to a wrong signed line, or make a
refusal touch the session, log or role. Then run pytest on a copy. A mutant is killed when pytest fails.
Usage: scripts/mutate.py   Exit 0 only if every mutant is killed."""
import os, ast, copy, pathlib, shutil, subprocess, sys, tempfile, tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
FLIP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot,
        ast.IsNot: ast.Is, ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE, ast.LtE: ast.Gt}


def sites(tree, funcs):
    out = []
    for f in ast.walk(tree):
        if isinstance(f, ast.FunctionDef) and f.name in funcs:
            for n in ast.walk(f):
                if isinstance(n, ast.Compare):
                    out += [("cmp", n, k) for k in range(len(n.ops))]
                elif isinstance(n, ast.BoolOp):
                    out.append(("boolop", n, 0))
                elif isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
                    out.append(("not", n, 0))
                elif isinstance(n, ast.Constant) and isinstance(n.value, bool):
                    out.append(("bool", n, 0))
                elif isinstance(n, ast.If) and any(isinstance(b, ast.Return) for b in n.body):
                    out.append(("guard", n, 0))
        if isinstance(f, ast.Assign) and getattr(f.targets[0], "id", "") == "PERMS":
            for kv, v in zip(f.value.keys, f.value.values):
                out += [("perm", v, k) for k in range(len(v.elts))]
        if isinstance(f, ast.Assign) and getattr(f.targets[0], "id", "") == "PATIENT_LINE":
            out += [("line", f.value, k) for k in range(len(f.value.values))]
        if isinstance(f, ast.FunctionDef) and f.name == "_refuse" and f.name in funcs:
            out += [("sess", f, k) for k in range(len(SESSION_HITS))]
    return out


# A refusal must leave session, log and role untouched: each of these is injected before _refuse returns.
SESSION_HITS = ["self.log.append(dict(self.log[-1]) if self.log else {'type': 'x'})", "self.log[-1:] = []",
                "object.__setattr__(self.session, 'role', 'clinician')",
                "object.__setattr__(self.session, 'actor', 'SYNTH-other')",
                "object.__setattr__(self.session, 'scope', ('x',))"]


class Unnot(ast.NodeTransformer):
    def __init__(self, target):
        self.t = target

    def visit_UnaryOp(self, n):
        self.generic_visit(n)
        return n.operand if n is self.t else n


def mutate(src, funcs, i):
    tree = ast.parse(src)
    kind, n, k = sites(tree, funcs)[i]
    if kind == "cmp":
        n.ops[k] = FLIP.get(type(n.ops[k]), ast.Eq)()
    elif kind == "boolop":
        n.op = ast.Or() if isinstance(n.op, ast.And) else ast.And()
    elif kind == "not":
        tree = Unnot(n).visit(tree)
    elif kind == "bool":
        n.value = not n.value
    elif kind == "guard":
        n.body = [ast.Pass()]
    elif kind == "line":
        vals = sorted({v.value for v in n.values})
        v = n.values[k]
        kind += ":" + n.keys[k].value
        v.value = next(x for x in vals if x != v.value)
    elif kind == "sess":
        kind += ":" + SESSION_HITS[k]
        n.body.insert(len(n.body) - 1, ast.parse(SESSION_HITS[k]).body[0])
    elif kind == "perm":
        kind += ":" + n.elts[k].value
        del n.elts[k]
    else:
        kind += f"#{k}"
    return f"{kind}@{getattr(n, 'lineno', '?')}", ast.unparse(ast.fix_missing_locations(tree))


sys.path.insert(0, str(ROOT / "scripts"))
START = __import__("safety_stamp").digest(ROOT)      # stamp only what was mutated: the sources as they were at start


def main(argv):
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    cfg = tomllib.loads((ROOT / "safety_functions.toml").read_text())
    mod, funcs = cfg["module"], set(cfg["functions"])
    src = (ROOT / mod).read_text()
    total = len(sites(ast.parse(src), funcs))
    survivors = []
    with tempfile.TemporaryDirectory() as td:
        work = pathlib.Path(td) / "w"
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        env = dict(os.environ, WARD_SIBLINGS_DIR=os.environ.get("WARD_SIBLINGS_DIR") or str(ROOT.parent))
        if subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"], cwd=work,
                          capture_output=True, env=env).returncode:
            print("baseline: the unmutated copy fails its tests; refusing to count mutants")
            return 1
        for i in range(total):
            label, code = mutate(src, funcs, i)
            (work / mod).write_text(code)
            r = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"],
                               cwd=work, capture_output=True,
                               env=dict(os.environ, WARD_SIBLINGS_DIR=os.environ.get("WARD_SIBLINGS_DIR") or str(ROOT.parent)))
            if r.returncode == 0:
                survivors.append(label)
        (work / mod).write_text(src)
    killed = total - len(survivors)
    for s in survivors:
        print(f"SURVIVED {mod} {s}")
    print(f"mutation {mod}: {killed}/{total} killed")
    if not survivors and __import__("safety_stamp").digest(ROOT) == START:   # unchanged while mutating
        __import__("safety_stamp").record(ROOT)
    return 0 if not survivors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
