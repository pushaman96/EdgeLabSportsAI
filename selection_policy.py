"""Shared shortlist preferences, explicit probability units and price arithmetic."""
import math

VERSION = 'probability-label-audit-v1'
HIGH_PROBABILITY_TIER = .60
MIN_EDGE = .05


def finite(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def price_probability(odds):
    odds = finite(odds)
    if odds is None or abs(odds) < 100:
        return None
    return 100/(odds+100) if odds > 0 else -odds/(-odds+100)


def annotate(original):
    row = dict(original)
    percent = finite(row.get('Estimated win %', row.get('Model win %')))
    p = percent/100 if percent is not None and 0 < percent < 100 else None
    be = price_probability(row.get('Odds'))
    row['Selection policy'] = VERSION
    row['Probability evidence'] = 'Model estimate; prospective calibration and profitability not established'
    row['Estimated loss %'] = round(100*(1-p), 2) if p is not None else None
    row['Probability tier'] = ('Higher model probability — experimental' if p >= HIGH_PROBABILITY_TIER
                               else 'Lower-probability value research') if p is not None else 'No valid probability'
    if be is not None:
        row['Break-even %'] = round(100*be, 2)
    if p is not None and be is not None:
        row['Model edge (pp)'] = round(100*(p-be), 2)
        row['Expected return per unit'] = p/be-1
    row['Main shortlist eligible'] = bool(row.get('Decision') != 'Pass' and p is not None and be is not None
                                          and p-be >= MIN_EDGE-1e-12)
    row['Value research eligible'] = bool(row.get('Decision') != 'Pass' and p is not None and be is not None
                                         and p < HIGH_PROBABILITY_TIER and p-be >= MIN_EDGE-1e-12)
    return row


def apply(rows):
    output = []
    for original in rows:
        row = annotate(original)
        output.append(row)
    return output


def render_research(rows, sport):
    import streamlit as st
    research = [r for r in rows if r.get('Value research eligible')]
    with st.expander(sport+' probability and price audit'):
        st.caption('Probability tiers describe model estimates, not verified hit rates. Existing selection rules remain unchanged. A favorable payout can qualify a lower-probability value selection; it must not be mistaken for a high-probability pick. Different prices or lines require a fresh calculation.')
        if research:
            fields = ('Game','Player','Category','Selection','Line','Odds','Estimated win %','Estimated loss %','Break-even %','Model edge (pp)','Probability tier','Reason')
            st.dataframe([{k:r.get(k) for k in fields} for r in research], hide_index=True, use_container_width=True)
        else:
            st.info('No qualifying lower-probability value research in this analysis.')
