"""Candidate scoring after policy eligibility; the model may rank, never permit."""
from dataclasses import dataclass
from models import RecoveryStrategy
from agent.recovery_model import RecoveryPropensityModel, feature_row

@dataclass(frozen=True)
class CandidateScore:
    strategy: RecoveryStrategy; probability: float; expected_value: int; allowed: bool; reason: str

def rank_candidates(failure_class, amount_paise, method, retries, risk_type, merchant_segment="standard") -> list[CandidateScore]:
    candidates = [RecoveryStrategy.RETRY_PAYMENT_LINK, RecoveryStrategy.ALTERNATE_METHOD_LINK, RecoveryStrategy.SEND_REMINDER,
                  RecoveryStrategy.REQUEST_MANDATE_UPDATE, RecoveryStrategy.COLLECT_RECEIVABLE_LINK, RecoveryStrategy.ESCALATE_TO_HUMAN, RecoveryStrategy.NO_ACTION]
    model = RecoveryPropensityModel(); output=[]
    friction = {RecoveryStrategy.RETRY_PAYMENT_LINK: 100, RecoveryStrategy.ALTERNATE_METHOD_LINK: 150, RecoveryStrategy.SEND_REMINDER: 50,
                RecoveryStrategy.REQUEST_MANDATE_UPDATE: 75, RecoveryStrategy.COLLECT_RECEIVABLE_LINK: 125, RecoveryStrategy.ESCALATE_TO_HUMAN: 500, RecoveryStrategy.NO_ACTION: 0}
    for candidate in candidates:
        row = feature_row(failure_class=failure_class.value, method=method or "unknown", amount_paise=amount_paise, retry_count=retries,
                          merchant_segment=merchant_segment, risk_type=risk_type, candidate_strategy=candidate.value)
        prediction = model.predict(row)
        # Actions that cannot collect directly have no claimed immediate recovery value.
        eligible = candidate not in {RecoveryStrategy.SEND_REMINDER, RecoveryStrategy.REQUEST_MANDATE_UPDATE, RecoveryStrategy.ESCALATE_TO_HUMAN, RecoveryStrategy.NO_ACTION}
        value = round(prediction.probability * amount_paise - friction[candidate]) if eligible else 0
        output.append(CandidateScore(candidate, prediction.probability, value, eligible, "ranked after deterministic policy" if eligible else "non-collecting or no-action candidate"))
    return sorted(output, key=lambda item: item.expected_value, reverse=True)
