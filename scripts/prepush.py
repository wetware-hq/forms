#!/usr/bin/env python3
"""Pre-push check, installed as .git/hooks/pre-push and run in CI. Fails if WORDING.md differs from what
sync_wording.py would make from the signed file (or, with --ci where there is no signed file, if WORDING.md does not
match its own header hash), or if any tracked file holds an internal name or a local workspace path, or if an answer file (truth.toml,
patient_wording.md, anything under stack_truth/) or a local settings file is tracked.

    python3 scripts/prepush.py SIGNED.md
    python3 scripts/prepush.py --ci"""
import pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sync_wording
import safety_stamp

# Internal names that must never reach the public repo. Built from parts so this file does not trip itself.
FORBIDDEN = [re.compile(p) for p in (r"\bB" + r"IO\b", r"/work" + r"space\b", r"\bheld" + r"out\d", r"patient-" + r"store")]


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / f for f in out.split()]


def answer_files(paths):
    """Tracked answer files or local settings: never committed."""
    return [p for p in paths if p.name in ("truth.toml", "patient_wording.md", "stack.local.toml") or "stack_truth" in p.parts]


def main(argv):
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    problems = []
    have = (ROOT / "WORDING.md").read_text()
    if argv[1] == "--ci":
        head, _, body = have.partition("\n\n")
        if not head.endswith("sha256: " + __import__("hashlib").sha256(body.encode()).hexdigest()):
            problems.append("WORDING.md does not match its header hash")
    elif have != sync_wording.render(pathlib.Path(argv[1]).read_text(), sync_wording.current_pending()):
        problems.append("WORDING.md differs from the signed file: run scripts/sync_wording.py")
    problems += [f"{p.relative_to(ROOT)}: answer file or local setting committed" for p in answer_files(tracked())]
    for p in tracked():
        try:
            text = p.read_text()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for rx in FORBIDDEN:
            for m in rx.finditer(text):
                problems.append(f"{p.relative_to(ROOT)}:{text.count(chr(10), 0, m.start()) + 1}: internal name or path")
    stale = safety_stamp.problem(ROOT)
    problems += [stale] if stale else []
    for x in problems:
        print(x)
    print(f"prepush: {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
