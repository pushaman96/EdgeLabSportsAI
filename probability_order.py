"""Display ordering only. Never changes probabilities, picks or quoted prices."""
import math

def probability_value(row,key):
    value=row.get(key)
    if isinstance(value,bool):return None
    try:value=float(value)
    except (TypeError,ValueError):return None
    return value if math.isfinite(value) and 0<=value<=(1 if key=='probability' else 100) else None

def highest_probability(rows,key,decision_key=None):
    def sort_key(row):
        value=probability_value(row,key)
        passed=str(row.get(decision_key,'')).lower().startswith('pass') if decision_key else False
        return passed,value is None,-value if value is not None else 0
    return sorted(rows,key=sort_key)
