#!/usr/bin/env python3
"""Simple mutation testing of the gate and permission code. For each mutant: flip a comparison,
swap and/or, drop a 'not', flip a True/False, remove a guard return, or remove one action from the
permission table. Then run pytest on a copy. A mutant is killed when pytest fails.
Usage: scripts/mutate.py MODULE.py func[,func...]   Exit 0 only if every mutant is killed."""
import ast, copy, pathlib, shutil, subprocess, sys, tempfile

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
    return out


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
    elif kind == "perm":
        kind += ":" + n.elts[k].value
        del n.elts[k]
    else:
        kind += f"#{k}"
    return f"{kind}@{getattr(n, 'lineno', '?')}", ast.unparse(ast.fix_missing_locations(tree))


def main(argv):
    mod, funcs = argv[1], set(argv[2].split(","))
    src = (ROOT / mod).read_text()
    total = len(sites(ast.parse(src), funcs))
    survivors = []
    with tempfile.TemporaryDirectory() as td:
        work = pathlib.Path(td) / "w"
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        for i in range(total):
            label, code = mutate(src, funcs, i)
            (work / mod).write_text(code)
            r = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"],
                               cwd=work, capture_output=True)
            if r.returncode == 0:
                survivors.append(label)
        (work / mod).write_text(src)
    killed = total - len(survivors)
    for s in survivors:
        print(f"SURVIVED {mod} {s}")
    print(f"mutation {mod}: {killed}/{total} killed")
    return 0 if not survivors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
