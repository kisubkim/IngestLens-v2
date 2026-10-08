"""Rule classification of page features. The features themselves are measured by the PDF engine (tools/toolpdf.py)."""


# Condition key -> (feature name, comparison). "min_" means feature >= value, "max_" means <=.
def _check(features: dict, key: str, value: float) -> tuple[bool, float]:
    kind, name = key.split("_", 1)
    actual = features[name]
    ok = actual >= value if kind == "min" else actual <= value
    # Margin relative to the threshold, used for confidence: 0 at the threshold, 1 when far past it.
    denom = abs(value) or 1.0
    margin = (actual - value) / denom if kind == "min" else (value - actual) / denom
    return ok, margin


def classify(features: dict, profiler_rules: dict) -> dict:
    """First matching rule wins. Returns label, rule id, confidence and per-condition evidence."""
    evidence = []
    for rule in profiler_rules["rules"]:
        checks = {k: _check(features, k, v) for k, v in rule["when"].items()}
        evidence.append({"rule": rule["id"], "matched": all(ok for ok, _ in checks.values())})
        if all(ok for ok, _ in checks.values()):
            weakest = min(m for _, m in checks.values())
            confidence = round(0.5 + 0.5 * min(weakest, 1.0), 2)
            return {
                "label": rule["label"],
                "rule_id": rule["id"],
                "confidence": confidence,
                "conditions": {k: {"threshold": rule["when"][k], "actual": features[k.split("_", 1)[1]]} for k in checks},
                "evaluated": evidence,
            }
    default = profiler_rules["default"]
    return {"label": default["label"], "rule_id": default["id"], "confidence": 0.4, "conditions": {}, "evaluated": evidence}


def body_font_size(size_hist: dict) -> float | None:
    """Most common span size weighted by characters."""
    if not size_hist:
        return None
    return float(max(size_hist.items(), key=lambda kv: kv[1])[0])
