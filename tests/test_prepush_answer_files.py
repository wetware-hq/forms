"""Pre-push refuses any tracked answer file or local setting (room ruling 08:08)."""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import prepush


def test_answer_files_refused():
    root = pathlib.Path("/r")
    got = prepush.answer_files([root / "stack_truth" / "S01" / "notes.md", root / "x" / "truth.toml",
                                root / "patient_wording.md", root / "stack.local.toml", root / "truth.md", root / "a.py"])
    assert [p.name for p in got] == ["notes.md", "truth.toml", "patient_wording.md", "stack.local.toml"]


def test_repo_has_no_answer_files():
    root = prepush.ROOT
    files = prepush.tracked() if (root / ".git").exists() else \
        [f for f in root.rglob("*") if f.is_file() and ".venv" not in f.parts and "__pycache__" not in f.parts]
    assert files and prepush.answer_files(files) == []


def test_prepush_fails_on_stale_mutation_stamp(monkeypatch, capsys):
    monkeypatch.setattr(prepush.safety_stamp, "problem", lambda root: "mutation.stamp: STALE-ZZ")
    monkeypatch.setattr(prepush, "tracked", lambda: [])
    assert prepush.main(["prepush", "--ci"]) == 1 and "STALE-ZZ" in capsys.readouterr().out
