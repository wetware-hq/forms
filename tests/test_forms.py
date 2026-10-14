import copy, json, pathlib, sys, tomllib
import pytest
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
import forms as F

EX = ROOT / "examples"
S = tomllib.loads((EX / "pre_procedure_safety.toml").read_text())

def bad_schema(fn):
    d = copy.deepcopy(S); fn(d)
    with pytest.raises(F.Invalid):
        F.check_schema(d)

@pytest.mark.parametrize("p", sorted(EX.glob("*.toml")))
def test_examples_build(p):
    assert F.main(["f", "build", str(p)]) == 0

def test_schema_rejections():
    bad_schema(lambda d: d.pop("form_id"))
    bad_schema(lambda d: d.update(extra="x"))
    bad_schema(lambda d: d.update(form_id=""))
    bad_schema(lambda d: d.update(version=1))
    bad_schema(lambda d: d.update(question=[]))
    bad_schema(lambda d: d["question"].append(dict(d["question"][0])))          # duplicate id
    bad_schema(lambda d: d["question"][0].update(id="Bad Id"))
    bad_schema(lambda d: d["question"][0].update(id=3))
    bad_schema(lambda d: d["question"][0].update(text="Consent signed."))     # not a question
    bad_schema(lambda d: d["question"][0].update(type="int"))                   # extra key
    bad_schema(lambda d: d["question"][0].pop("text"))

@pytest.mark.parametrize("v", [1, 0, "true", "yes", None, 1.0])
def test_non_bool_rejected(v):
    r = F.new_response(S)
    with pytest.raises(F.Invalid):
        F.set_answer(r, S, "consent_signed", v)
    assert r["answered"] == 0

def test_unknown_id_rejected():
    with pytest.raises(F.Invalid):
        F.set_answer(F.new_response(S), S, "nope", True)

def test_unanswered_distinct_from_no():
    r = F.new_response(S)
    F.set_answer(r, S, "consent_signed", False)
    a = F.export(r, S)["answers"]
    assert a["consent_signed"] is False and a["site_marked"] is None
    F.set_answer(r, S, "consent_signed", True)
    assert F.export(r, S)["answers"]["consent_signed"] is True
    F.set_answer(r, S, "consent_signed", False)
    assert r["value"] == 0 and r["answered"] == 2

def test_response_rejections():
    good = F.new_response(S)
    for k, v in [("schema_hash", "0" * 64), ("n", 99), ("answered", -1), ("answered", True),
                 ("answered", 1 << 6), ("value", "1"), ("version", "2")]:
        r = dict(good, **{k: v})
        with pytest.raises(F.Invalid):
            F.check_response(r, S)
    with pytest.raises(F.Invalid):
        F.check_response(dict(good, value=1), S)          # yes on unanswered
    with pytest.raises(F.Invalid):
        F.check_response({k: v for k, v in good.items() if k != "n"}, S)

def test_hash_bound_to_schema():
    d = copy.deepcopy(S); d["question"][0]["text"] = "Changed?"
    with pytest.raises(F.Invalid):
        F.check_response(F.new_response(S), d)

def test_cli_flow(tmp_path, capsys):
    sp, rp = str(EX / "pre_procedure_safety.toml"), str(tmp_path / "r.json")
    assert F.main(["f", "status", sp, rp]) == 1
    assert F.main(["f", "fill", sp, rp, "consent_signed=true", "site_marked=false"]) == 1
    ids = [q["id"] for q in S["question"]]
    assert F.main(["f", "fill", sp, rp] + [f"{i}=true" for i in ids]) == 0
    assert F.main(["f", "status", sp, rp]) == 0
    capsys.readouterr()
    assert F.main(["f", "export", sp, rp]) == 0
    out = json.loads(capsys.readouterr().out)
    assert all(v is True for v in out["answers"].values())

@pytest.mark.parametrize("arg", ["consent_signed=1", "consent_signed=yes", "consent_signed=", "consent_signed", "nope=true"])
def test_cli_fill_rejections(tmp_path, arg):
    rp = tmp_path / "r.json"
    assert F.main(["f", "fill", str(EX / "pre_procedure_safety.toml"), str(rp), arg]) == 2
    assert not rp.exists()

def test_cli_invalid_cases(tmp_path):
    sp = str(EX / "pre_procedure_safety.toml")
    assert F.main(["f"]) == 2
    assert F.main(["f", "fill", sp, str(tmp_path / "r.json")]) == 2
    assert F.main(["f", "build", str(tmp_path / "missing.toml")]) == 2
    (tmp_path / "x.toml").write_text("[[question]\n")
    assert F.main(["f", "build", str(tmp_path / "x.toml")]) == 2
    (tmp_path / "r.json").write_text("{not json")
    assert F.main(["f", "status", sp, str(tmp_path / "r.json")]) == 2
    other = F.new_response(tomllib.loads((EX / "patient_history.toml").read_text()))
    (tmp_path / "o.json").write_text(json.dumps(other))
    assert F.main(["f", "status", sp, str(tmp_path / "o.json")]) == 2
