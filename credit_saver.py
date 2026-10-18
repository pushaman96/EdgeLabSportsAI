"""Conservative request budgets. Reading saved odds never needs an odds request."""
import math

def remaining_number(value):
    try:
        value=float(value)
        return value if math.isfinite(value) and value>=0 else None
    except (TypeError,ValueError):return None

def spending_allowed(mode,cost,budget,remaining=None):
    if mode=='Saved data only — 0 credits':return False,'Saved-data mode never requests new odds.'
    balance=remaining_number(remaining)
    if balance==0:return False,'Known credit balance is zero. Saved picks, scores and grading remain available.'
    if mode=='Credit-saving mode' and cost>budget:return False,'This load exceeds your per-click credit budget. Select fewer games/categories or increase the budget.'
    if balance is not None and cost>balance:return False,'The maximum request cost exceeds the last reported balance. Select fewer games/categories.'
    return True,''

def choose_targets(events,selected_ids,now):
    from datetime import datetime
    wanted=set(selected_ids)
    return [e for e in events if e['id'] in wanted and datetime.fromisoformat(e['commence_time'].replace('Z','+00:00'))>now]

def balance_record(previous,key_hash,remaining,checked):
    """Do not replace a newer balance check with an older cached response header."""
    from datetime import datetime
    if remaining_number(remaining) is None:return previous
    try:
        stamp=datetime.fromisoformat(checked.replace('Z','+00:00'))
        if previous and previous.get('key_hash')==key_hash:
            old=datetime.fromisoformat(previous['checked'].replace('Z','+00:00'))
            if old>stamp:return previous
    except (ValueError,TypeError,KeyError):return previous
    return {'key_hash':key_hash,'remaining':remaining,'checked':checked}
