DEC_PREFIX = "DEC"
REQ_PREFIX = "REQ"
TSK_PREFIX = "TSK"
RSK_PREFIX = "RSK"
OQ_PREFIX = "OQ"
PLAN_PREFIX = "PLAN"
STEP_PREFIX = "STEP"

_ID_PATTERN = r"^{prefix}-\d{{3,}}$"


def id_pattern(prefix: str) -> str:
    return _ID_PATTERN.format(prefix=prefix)


def format_item_id(prefix: str, number: int) -> str:
    """Build a stable, human-referenceable item ID such as DEC-001."""
    if number < 1:
        raise ValueError("Item numbers must start at 1.")
    return f"{prefix}-{number:03d}"
