"""Combine embedding similarity + rule filters into a 0-100 score with reasons."""
from dataclasses import dataclass, field

from app.matching import embeddings
from app.matching.rules import apply_rules


@dataclass
class ScoreResult:
    score: float
    reasons: list[str] = field(default_factory=list)


def score_job(
    resume_text: str,
    title: str,
    description: str,
    location: str,
    remote: bool,
    rules: dict,
) -> ScoreResult:
    rule_result = apply_rules(title, description, location, remote, rules)
    if not rule_result.passed:
        return ScoreResult(score=0.0, reasons=rule_result.reasons)

    sim = embeddings.similarity(resume_text, f"{title}\n\n{description}")
    base = round(sim * 100, 1)
    score = max(0.0, min(100.0, base + rule_result.bonus))
    reasons = [f"similarity {base}/100 ({embeddings.backend_name()})"] + rule_result.reasons
    if rule_result.bonus:
        reasons.append(f"rule bonus +{rule_result.bonus:g}")
    return ScoreResult(score=round(score, 1), reasons=reasons)
