"""One test per register row (RULES.md). Synthetic data only."""
import copy, json, pathlib, random, sys, tomllib
import pytest
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
import forms as F
from messages import msg

EX = ROOT / "examples"
PH, PP = str(EX / "patient_history.toml"), str(EX / "pre_procedure_safety.toml")
SPH = tomllib.loads(pathlib.Path(PH).read_text())
TS = "1936-05-02T09:00"
EP = "SYNTH-EP-0001"

def env(case=PH, role="patient", ep=EP, actor="SYNTH-person-01"):
    e = F.FormEnv(); e.reset(case, actor, role, ep); return e

def ans(i, v):
    return {"type": "answer", "question_id": i, "value": v, "timestamp": TS}

def bad_schema(fn):
    d = copy.deepcopy(SPH); fn(d)
    with pytest.raises(F.Invalid) as e:
        F.check_schema(d)
    return str(e.value)

def scripted_patient(e):
    """Deterministic agent: answers each next question from a fixed script, declines what is not scripted."""
    script = {"allergy_any": False, "takes_blood_thinner": True, "smokes": False}
    while (q := e.step({"type": "next"})["next"]):
        a = ans(q, script[q]) if q in script else {"type": "decline", "question_id": q, "timestamp": TS}
        assert e.step(a)["accepted"]

# ---------- signed rules ----------
def test_question_fields_required():
    for k in ("id", "version", "text", "safety_critical", "clinician_must_confirm"):
        assert bad_schema(lambda d: d["question"][0].pop(k)).startswith("ERR:")
    bad_schema(lambda d: d["question"][0].update(extra=1))
    bad_schema(lambda d: d["question"][0].update(safety_critical="yes"))

def test_ask_if_only_way_not_applicable():
    e = env(); e.step(ans("allergy_any", False))
    assert e.check()["not_applicable"] == ["allergy_reaction_severe"]
    e2 = env()
    assert e2.check()["not_applicable"] == []          # parent unanswered: still asked

def test_negative_wording_refused():
    for t in ("Do you have no allergies?", "Is it not marked?", "Never smoked?", "Without pain?", "None today?", "Can't walk?"):
        assert bad_schema(lambda d: d["question"][0].update(text=t)) == msg("CK-NEGATIVE", n=1)

def test_bitsets_derived_from_log():
    e = env(); e.step(ans("allergy_any", True)); e.step(ans("smokes", False))
    assert e.bitsets()["answered"] == 0b1001 and e.bitsets()["value"] == 0b0001
    e.log.clear()
    assert e.bitsets()["answered"] == 0

def test_answer_event_fields():
    e = env(); e.step(ans("smokes", True))
    assert set(e.log[0]) == {"type", "question_id", "question_version", "value", "source", "actor", "timestamp", "episode_id"}
    assert e.step({"type": "answer", "question_id": "smokes", "value": True})["accepted"] is False

@pytest.mark.parametrize("v", [1, 0, "true", None, 1.0])
def test_value_strict_bool(v):
    e = env(); r = e.step(ans("smokes", v))
    assert r == {"accepted": False, "reason": msg("RF-NOT-BOOL")} and e.log == []

def test_decline_never_read_as_no():
    e = env(); e.step({"type": "decline", "question_id": "smokes", "timestamp": TS})
    assert "value" not in e.log[0]
    assert e.check()["answers"]["smokes"] == "declined" and e.bitsets()["answered"] == 0
    assert e.patient_view()["smokes"] == msg("PV-DECLINED")

def test_agent_answer_needs_patient_confirm():
    a = env(role="agent"); a.step(ans("smokes", False))
    assert "smokes" in a.check()["open"]
    assert a.patient_view()["smokes"].startswith(msg("PV-ANS-AGENT"))
    p = env(); p.replay(a.log)
    assert p.step({"type": "confirm", "question_id": "smokes", "timestamp": TS})["accepted"]
    assert "smokes" not in p.check()["open"]

def test_stale_or_foreign_answer_reverts():
    e = env(); e.step(ans("smokes", True))
    for change in ({"question_version": "0"}, {"episode_id": "SYNTH-EP-OTHER"}):
        log = e.log + [dict(e.log[0], **change)]
        f = env(); f.replay(log)
        assert f.check()["answers"]["smokes"] == "unanswered"
        assert f.patient_view()["smokes"] == msg("PV-REASK")

def test_clinician_must_confirm_needs_clinician():
    a = env(PP, "agent"); a.step(ans("consent_signed", True))
    assert "consent_signed" in a.check()["open"]
    c = env(PP, "clinician"); c.step(ans("consent_signed", True))
    assert "consent_signed" not in c.check()["open"]

def test_decline_blocks_only_clinician_must_confirm():
    e = env(PP, "patient")
    e.step({"type": "decline", "question_id": "fasting_confirmed", "timestamp": TS})
    e.step({"type": "decline", "question_id": "consent_signed", "timestamp": TS})
    o = e.check()["open"]
    assert "fasting_confirmed" not in o and "consent_signed" in o

def test_alert_answer_flags_any_polarity():
    e = env(PP, "clinician"); e.step(ans("consent_signed", False)); e.step(ans("anticoagulant_present", True))
    f = e.check()["flags"]
    assert msg("FL-ALERT", n=2, yesno=False) in f and msg("FL-ALERT", n=6, yesno=True) in f

def test_safety_critical_unanswered_or_declined_alerts():
    e = env(); e.step({"type": "decline", "question_id": "allergy_any", "timestamp": TS})
    f = e.check()["flags"]
    assert msg("FL-DECLINED", n=1) in f and msg("FL-UNKNOWN", n=2) in f

def test_agents_never_infer():
    a = env(role="agent"); a.step(ans("allergy_any", False))
    assert a.check()["answers"]["takes_blood_thinner"] == "unanswered" and len(a.log) == 1
    assert a.check()["answers"]["allergy_reaction_severe"] == "n/a"   # skipped, not answered

def test_no_who_content():
    for p in list(ROOT.glob("*.py")) + list(EX.glob("*")) + [ROOT / "README.md"]:
        t = p.read_text()
        assert "World Health Organization" not in t and " WHO " not in t, p

def test_schema_unique_ids():
    assert bad_schema(lambda d: d["question"].append(dict(d["question"][0]))) == "ERR:duplicate_question_id"

def test_schema_hash_bound():
    d = copy.deepcopy(SPH); d["question"][0]["version"] = "9"
    assert F.schema_hash(d) != F.schema_hash(SPH) and env().bitsets()["schema_hash"] == F.schema_hash(SPH)

def test_status_exit_codes(tmp_path):
    log = str(tmp_path / "l.jsonl")
    assert F.main(["f", "status", PP, log, EP]) == 1
    assert F.main(["f", "answer", PP, log, EP, "clinician", "SYNTH-dr", TS] +
                  [f"{q['id']}=true" for q in tomllib.loads(pathlib.Path(PP).read_text())["question"]]) == 0
    assert F.main(["f", "status", PP, log, EP]) == 0
    assert F.main(["f", "answer", PP, log, EP, "clinician", "SYNTH-dr", TS, "site_marked=1"]) == 2
    assert F.main(["f"]) == 2

def test_export_json(tmp_path, capsys):
    log = str(tmp_path / "l.jsonl")
    F.main(["f", "answer", PH, log, EP, "patient", "SYNTH-p", TS, "smokes=false"]); capsys.readouterr()
    assert F.main(["f", "export", PH, log, EP]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["answers"]["smokes"] is False and out["bitsets"]["answered"] == 0b01000

def test_rejected_actions_not_logged():
    e = env()
    for a in ({"type": "erase"}, ans("ghost", True), ans("smokes", "yes")):
        assert not e.step(a)["accepted"]
    assert e.log == []

def test_decline_confirm_patient_only():
    e = env(role="clinician")
    for t in ("decline", "confirm"):
        e2 = F.FormEnv(); e2.reset(PH, "x", "clinician", EP)
        assert e2.step({"type": t, "question_id": "smokes", "timestamp": TS})["reason"] == msg("RF-ROLE-CONFIRM")

def test_replay_equality():
    e = env(); scripted_patient(e)
    f = env(); assert f.replay(e.log) == e.check() and f.log == e.log

def test_observe_isolated_episode():
    a, b = env(ep="SYNTH-EP-A"), env(ep="SYNTH-EP-B")
    a.step(ans("smokes", True))
    assert "smokes" in b.observe()["open"] and b.observe()["episode_id"] == "SYNTH-EP-B"

@pytest.mark.parametrize("p", [PH, PP])
def test_examples_build(p):
    assert F.main(["f", "build", p]) == 0

def test_scripted_agent_episode():
    e = env(); scripted_patient(e)
    c = e.check()
    assert c["complete"] and c["not_applicable"] == ["allergy_reaction_severe"]
    assert msg("FL-ALERT", n=3, yesno=True) in c["flags"]

# ---------- wording lines ----------
def test_line_pv_ans_self():
    e = env(); e.step(ans("smokes", False)); assert e.patient_view()["smokes"] == msg("PV-ANS-SELF")

def test_line_pv_ans_agent():
    e = env(role="agent"); e.step(ans("smokes", False))
    assert e.patient_view()["smokes"].startswith("Your assistant answered. You haven't checked this yet.")

def test_line_pv_declined():
    test_decline_never_read_as_no()

def test_line_pv_skipped():
    e = env(); e.step(ans("allergy_any", False))
    assert e.patient_view()["allergy_reaction_severe"] == "Not asked, because you said you have no medicine allergies"

def test_line_pv_open():
    assert env().patient_view()["smokes"] == "Not answered yet"

def test_line_pv_reask():
    test_stale_or_foreign_answer_reverts()

def test_line_pv_confirm():
    e = env(role="agent"); e.step(ans("smokes", True))
    assert e.patient_view()["smokes"].endswith("Your assistant answered Yes. Is that right?")

def test_line_rf_role_confirm():
    test_decline_confirm_patient_only()

def test_line_rf_not_bool():
    assert env().step(ans("smokes", 1))["reason"] == "Refused: answers must be Yes or No."

def test_line_ck_two_facts():
    assert bad_schema(lambda d: d["question"][3].update(text="Do you smoke or drink?")) == msg("CK-TWO-FACTS", n=4)

def test_line_ck_negative():
    assert bad_schema(lambda d: d["question"][0].update(text="Is it not done?")) == "Question 1 is worded as a negative. Reword it as a plain question."

def test_line_ck_no_alert():
    assert bad_schema(lambda d: d["question"][1].pop("alert_answer")) == "Question 2 has no alert answer set."

def test_line_ck_cond_order():
    assert bad_schema(lambda d: d["question"][1]["ask_if"].update(id="smokes")) == msg("CK-COND-ORDER", n=2)

def test_line_ck_cond_words():
    assert bad_schema(lambda d: d["question"][1]["ask_if"].pop("wording")) == msg("CK-COND-WORDS", n=2)

def test_line_bk_unanswered():
    assert env().check()["blocked"][0] == "Not finished: 5 questions still need an answer."

def test_line_bk_clin_confirm():
    assert msg("BK-CLIN-CONFIRM", n=1) in env(PP, "agent").check()["blocked"]

def test_line_bk_stale():
    e = env(); r = e.step(dict(ans("smokes", True), episode_id="SYNTH-EP-X"))
    assert r["reason"] == msg("BK-STALE", n=4)
    assert e.step(ans("smokes", True))["accepted"]
    f = env(); f.replay([dict(e.log[0], question_version="0")]); assert msg("BK-STALE", n=4) in f.check()["blocked"]

def test_line_fl_alert():
    test_alert_answer_flags_any_polarity()

def test_line_fl_unknown():
    assert msg("FL-UNKNOWN", n=1) in env().check()["flags"]

def test_line_fl_declined():
    test_safety_critical_unanswered_or_declined_alerts()
