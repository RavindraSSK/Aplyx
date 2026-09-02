"""Rule filters from targets.yaml applied on top of the similarity score."""
from dataclasses import dataclass, field

SPONSORSHIP_TERMS = ("sponsorship", "sponsor visas", "visa sponsor", "work authorization")


@dataclass
class RuleResult:
    passed: bool = True
    reasons: list[str] = field(default_factory=list)
    bonus: float = 0.0  # additive points on top of similarity score


def apply_rules(title: str, description: str, location: str, remote: bool, rules: dict) -> RuleResult:
    """Evaluate the `matching` section of targets.yaml against one job.

    Hard failures (excluded keyword, missing required title keyword, location
    mismatch, missing sponsorship mention when required) zero the score.
    """
    result = RuleResult()
    title_l = title.lower()
    desc_l = description.lower()
    loc_l = location.lower()

    required = [k.lower() for k in rules.get("required_title_keywords", [])]
    if required:
        hits = [k for k in required if k in title_l]
        if not hits:
            result.passed = False
            result.reasons.append(f"title lacks required keywords {required}")
        else:
            result.bonus += 5.0
            result.reasons.append(f"title matches keyword(s): {', '.join(hits)}")

    for kw in rules.get("excluded_keywords", []):
        kw_l = kw.lower()
        if kw_l in title_l or kw_l in desc_l:
            result.passed = False
            result.reasons.append(f"excluded keyword found: '{kw}'")

    allowed_locations = [loc.lower() for loc in rules.get("locations", [])]
    if allowed_locations:
        if remote or any(loc in loc_l for loc in allowed_locations):
            result.reasons.append("location ok" + (" (remote)" if remote else ""))
        else:
            result.passed = False
            result.reasons.append(f"location '{location}' not in {rules.get('locations')}")

    if rules.get("must_mention_sponsorship", False):
        if any(term in desc_l for term in SPONSORSHIP_TERMS):
            result.reasons.append("mentions sponsorship")
        else:
            result.passed = False
            result.reasons.append("does not mention visa sponsorship")

    return result
