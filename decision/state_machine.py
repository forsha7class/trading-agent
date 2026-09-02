import logging
import time
logger = logging.getLogger(__name__)

STATES = ["DATA_INVALID","DATA_VALID","ANALYZING","SIGNAL_GENERATED","RISK_CHECK","AI_REVIEW","DECISION"]
# allowed transitions (minimal)
TRANSITIONS = {
    "DATA_INVALID": ["DATA_INVALID","DATA_VALID","DECISION"],
    "DATA_VALID": ["ANALYZING","DATA_INVALID","DECISION"],
    "ANALYZING": ["SIGNAL_GENERATED","DATA_INVALID","DECISION"],
    "SIGNAL_GENERATED": ["RISK_CHECK","DECISION"],
    "RISK_CHECK": ["AI_REVIEW","DECISION"],
    "AI_REVIEW": ["DECISION"],
    "DECISION": ["DATA_VALID","DATA_INVALID"],
}

class DecisionStateMachine:
    def __init__(self, initial: str = "DATA_INVALID"):
        if initial not in STATES:
            initial = "DATA_INVALID"
        self.state = initial
        self.history: list[dict] = []
        self._log(initial, "init")

    def _log(self, state, reason):
        entry = {"ts": time.time(), "state": state, "reason": reason}
        self.history.append(entry)
        logger.debug("state -> %s (%s)", state, reason)

    def transition(self, to: str, reason: str = "") -> bool:
        if to not in STATES:
            self._log(self.state, f"invalid transition target {to} -> NO_TRADE")
            return False
        # allow any transition to DECISION (fail-closed)
        if to == "DECISION" or to in TRANSITIONS.get(self.state, []):
            self.state = to
            self._log(to, reason)
            return True
        # invalid transition => log and stay, default to DECISION on critical
        self._log(self.state, f"blocked {self.state}->{to}: {reason}")
        return False

    def reset(self, reason: str = "reset"):
        self.state = "DATA_INVALID"
        self._log(self.state, reason)

    @property
    def is_terminal(self) -> bool:
        return self.state == "DECISION"
