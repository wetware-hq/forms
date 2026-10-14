import pathlib, sys
import pytest
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
import forms as F

CASE = str(ROOT / "examples" / "patient_history.toml")

def scripted_patient_agent(env):
    """Deterministic agent: ask 'next', answer by a fixed rule, decline one, then confirm."""
    rule = {"allergy_any": True, "takes_blood_thinner": False, "diabetes": False, "smokes": False,
            "prior_surgery": True}
    while True:
        q = env.step({"type": "next"})["next"]
        if q is None:
            break
        a = {"type": "answer", "id": q, "value": rule[q]} if q in rule else {"type": "decline", "id": q}
        assert env.step(a)["accepted"]
    assert env.step({"type": "confirm"})["accepted"]

def test_scripted_episode_and_replay_equality():
    env = F.FormEnv(); env.reset(CASE, "SYNTH-agent-01", "patient", "SYNTH-EP-0001")
    scripted_patient_agent(env)
    c = env.check()
    assert c["complete"] and c["open"] == [] and c["flags"] == ["declined:pregnant_possible"]
    assert c["answers"]["allergy_any"] is True and c["answers"]["pregnant_possible"] is None
    before, log = env.state(), list(env.log)
    fresh = F.FormEnv(); fresh.reset(CASE, "SYNTH-agent-01", "patient", "SYNTH-EP-0001")
    assert fresh.replay(log) == before and fresh.check() == c and fresh.log == log

def test_clinician_cannot_decline_or_confirm():
    env = F.FormEnv(); env.reset(CASE, "SYNTH-dr-01", "clinician", "SYNTH-EP-0002")
    for a in ({"type": "decline", "id": "smokes"}, {"type": "confirm"}):
        r = env.step(a)
        assert not r["accepted"] and "patient only" in r["reason"]
    assert env.log == []

@pytest.mark.parametrize("a,why", [
    ({"type": "answer", "id": "smokes", "value": 1}, "bool"),
    ({"type": "answer", "id": "smokes", "value": None}, "bool"),
    ({"type": "answer", "id": "nope", "value": True}, "unknown question"),
    ({"type": "answer", "id": "smokes"}, "exactly"),
    ({"type": "delete"}, "unknown action"),
    ({"type": "confirm"}, "confirm blocked"),
])
def test_gate_rejections_do_not_log(a, why):
    env = F.FormEnv(); env.reset(CASE, "SYNTH-agent-01", "patient", "SYNTH-EP-0003")
    r = env.step(a)
    assert not r["accepted"] and why in r["reason"] and env.log == []

def test_no_changes_after_confirm():
    env = F.FormEnv(); env.reset(CASE, "SYNTH-agent-01", "patient", "SYNTH-EP-0004")
    scripted_patient_agent(env)
    assert env.step({"type": "answer", "id": "smokes", "value": True})["reason"] == "form already confirmed"

def test_episodes_isolated_and_foreign_log_rejected():
    a = F.FormEnv(); a.reset(CASE, "x", "patient", "SYNTH-EP-A")
    b = F.FormEnv(); b.reset(CASE, "y", "patient", "SYNTH-EP-B")
    a.step({"type": "answer", "id": "smokes", "value": True})
    assert "smokes" in b.observe()["open"] and b.observe()["episode_id"] == "SYNTH-EP-B"
    with pytest.raises(F.Invalid):
        b.replay(a.log)

def test_tampered_log_rejected_on_replay():
    env = F.FormEnv(); env.reset(CASE, "x", "clinician", "SYNTH-EP-C")
    bad = [{"episode_id": "SYNTH-EP-C", "actor": "x", "role": "clinician", "action": {"type": "confirm"}}]
    with pytest.raises(F.Invalid):
        env.replay(bad)
