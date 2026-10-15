"""Sessions and scope of practice. Roles are fixed when a session opens and never passed in a call."""
from dataclasses import dataclass
from messages import msg

ROLES = ("patient", "patient_agent", "clinician", "clinician_agent", "guardian")
AGENTS = ("patient_agent", "clinician_agent")


class Invalid(Exception):
    pass


@dataclass(frozen=True)
class Session:
    actor: str
    role: str
    discipline: str = None   # clinician only: a discipline named in the approved form or list data
    scope: tuple = ()        # clinician_agent only: disciplines of the clinician who granted it


def open_session(actor, role, discipline=None, scope=()):
    if role not in ROLES:
        raise Invalid(msg("RF-UNREGISTERED"))
    if not isinstance(actor, str) or not actor.strip():
        raise Invalid(msg("ER-BAD-FIELD", field="actor", item="session"))
    if (role == "clinician") != (isinstance(discipline, str) and bool(discipline.strip())):
        raise Invalid(msg("ER-BAD-FIELD", field="discipline", item="session"))
    scope = tuple(scope or ())
    if (role == "clinician_agent") != bool(scope) or not all(isinstance(x, str) and x for x in scope):
        raise Invalid(msg("ER-BAD-FIELD", field="scope", item="session"))
    return Session(actor, role, discipline, scope)


def disciplines(s):
    if s.role == "clinician":
        return {s.discipline}
    if s.role == "clinician_agent":
        return set(s.scope)
    return set()


def in_scope(s, allowed):
    return bool(disciplines(s) & set(allowed))
