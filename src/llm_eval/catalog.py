from .common import GIB, read_json


def validate_catalog(data):
    ids = set()
    for model in data["models"]:
        if model["id"] in ids:
            raise ValueError("Duplicate model ID")
        ids.add(model["id"])
        if not model["sources"] or not model["license"]:
            raise ValueError("Every model requires evidence and license classification")
        if model["status"] not in {"candidate", "conditional", "control", "excluded"}:
            raise ValueError("Invalid eligibility status")
    return data


def matrix(root):
    models = validate_catalog(read_json(root / "catalog/models.json"))["models"]
    platforms = read_json(root / "catalog/platforms.json")["platforms"]
    rows = []
    for model in models:
        for engine in platforms:
            for os_id, support in engine["os_support"].items():
                reason = []
                if model["status"] == "excluded":
                    reason.append("model_excluded")
                if support == "unsupported":
                    reason.append("os_unsupported")
                if model["id"] in engine.get("blocked_models", []):
                    reason.append("architecture_unsupported")
                state = "blocked" if reason else "requires_validation"
                if model["status"] == "control" and not reason:
                    state = "control_only"
                rows.append({"model": model["id"], "platform": engine["id"], "os": os_id,
                             "status": state, "os_support": support, "reason": ";".join(reason),
                             "model_validation": "not_measured", "target_precision": model["target_precision"]})
    return rows


def estimate_weights(parameters_b, bits):
    """Raw mathematical lower bound, not a RAM or artifact-size forecast."""
    return parameters_b * 1e9 * bits / 8 / GIB
