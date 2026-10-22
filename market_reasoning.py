"""Exact-market outcome reasoning. Illustrations never manufacture probabilities."""
import math
from selection_policy import finite,price_probability

VERSION='exact-market-reasoning-v1'
UNITS={'Passing yards':'passing yards','Rushing yards':'rushing yards','Receiving yards':'receiving yards','Receptions':'receptions','Passing attempts':'passing attempts','Rushing attempts':'rushing attempts','Passing completions':'completions','Passing interceptions':'interceptions thrown','Passing touchdowns':'passing touchdowns','Points':'points','Rebounds':'rebounds','Assists':'assists','Three-pointers made':'made three-pointers','Steals':'steals','Blocks':'blocks','PRA':'points + rebounds + assists','Game total points':'combined game points','Team total points':'team points','Team sacks':'team sacks'}
DRIVERS={
 'Receptions':'Targets × catch probability. Short catches can clear receptions while missing receiving yards.',
 'Receiving yards':'Targets × catch probability × yards per catch. Catch volume alone does not establish a yardage win.',
 'Rushing yards':'Carries × yards per carry. A rushing-attempt win can coexist with a rushing-yardage loss.',
 'Passing yards':'Attempts × completion probability × yards per completion. Attempts, completions and passing yards have different thresholds.',
 'Anytime touchdown':'Scoring opportunities and touchdown conversion; overall targets or yardage do not alone establish touchdown probability. A passing touchdown is not a touchdown scored by the passer.',
 'Passing touchdowns':'Passing scoring opportunities and conversion; passing yardage does not establish passing touchdowns.',
 'Passing interceptions':'Passing attempts and interception risk; an interception prop is distinct from passing yards and touchdowns.',
 'PRA':'Points + rebounds + assists, using their joint game outcomes. A points win does not establish a PRA win. Do not multiply component win probabilities.',
 'Three-pointers made':'Three-point attempts × conversion. Made threes are different from attempted threes and total points.',
 'Moneyline':'The selected team must win. A strong individual performance or high combined score does not establish the game winner.',
 'Game total points':'Both teams’ final points added together. Picking the winner does not establish whether the total clears.',
 'Team total points':'Only the selected team’s final points count; the opponent’s points do not count toward this line.',
 'Team sacks':'Opponent dropbacks, pass protection and defensive pressure/conversion; player sacks and team sacks are different markets.',
}


def outcome(category,direction,line,actual):
    """Illustrative settlement only; missing/invalid data never becomes zero."""
    if category=='Moneyline':
        return {'Win':'Win','Loss':'Loss','Tie':'Push'}.get(actual,'Unknown') if direction=='Win'else'Unknown'
    v=finite(actual);threshold=finite(line)
    signed=category in ('Passing yards','Rushing yards','Receiving yards')
    if v is None or (v<0 and not signed):return 'Unknown'
    if category=='Anytime touchdown':
        if line is not None and threshold is None:return 'Unknown'
        if direction not in ('Yes','Over','No','Under')or v!=int(v):return 'Unknown'
        if threshold not in (None,.5):return 'Unknown'
        return 'Win'if (v>=1)==(direction in ('Yes','Over'))else'Loss'
    if category not in UNITS or threshold is None or (threshold<0 and not signed) or direction not in ('Over','Under'):return 'Unknown'
    if v!=int(v):return 'Unknown'
    if v==threshold:return 'Push'
    return 'Win'if (v>threshold)==(direction=='Over')else'Loss'


def analysis(row):
    category=row.get('Category');direction=row.get('Selection');line=finite(row.get('Line'))
    signed=category in ('Passing yards','Rushing yards','Receiving yards')
    valid=category in UNITS and line is not None and (line>=0 or signed)and direction in ('Over','Under')
    rule='Unsupported or incomplete market: no outcome or probability inferred.'
    examples=[]
    if valid:
        unit=UNITS[category]
        if direction=='Over':rule=f'Wins at {math.floor(line)+1:g}+ {unit}.'
        else:rule=f'Wins at {math.ceil(line)-1:g} or fewer {unit}.'if line>0 or signed else 'Under 0 cannot win with a nonnegative final statistic.'
        rule+=' An exact '+f'{line:g}'+' is a push.'if line==int(line)else' Whole-number final statistics cannot equal this fractional line.'
        floor_value=math.ceil(line)-1 if signed else max(0,math.ceil(line)-1)
        values=sorted({floor_value,math.floor(line)+1}|({int(line)}if line==int(line)else set()))
        examples=[{'Actual':value,'Result':outcome(category,direction,line,value)}for value in values]
    elif category=='Anytime touchdown'and direction in ('Yes','Over','No','Under')and (row.get('Line')is None or line==.5):
        valid=True;rule='Wins if the player scores at least one touchdown.'if direction in ('Yes','Over')else'Wins if the player scores no touchdowns.'
        rule+=' Receiving yards and receptions alone do not settle this market.'
        examples=[{'Actual touchdowns scored':v,'Result':outcome(category,direction,line,v)}for v in (0,1)]
    elif category=='Moneyline'and direction=='Win':
        valid=True;rule='Wins if the selected team wins; a tie is illustrated as a push. Verify the sportsbook’s tie/overtime rules.'
        examples=[{'Actual team result':v,'Result':outcome(category,direction,line,v)}for v in ('Win','Loss','Tie')]
    percent=finite(row.get('Estimated win %',row.get('Model win %')))
    p=percent/100 if percent is not None and 0<percent<100 else None
    be=price_probability(row.get('Odds',row.get('Moneyline')))
    projection=finite(row.get('Projection (yards)'))
    if projection is None:projection=finite(row.get('Projection (count)'))
    if projection is None and category in ('Passing attempts','Rushing attempts'):projection=finite(row.get('Expected opportunities'))
    price='No usable quote-specific model probability and price pair; cannot establish value.'
    if valid and p is not None and be is not None:
        price=f'Existing model estimate {100*p:.1f}%; price break-even {100*be:.1f}%; difference {100*(p-be):+.1f} percentage points.'
        price+=' This arithmetic assumes the saved probability belongs to this exact selection, line and price; a changed line requires model reanalysis. Push probability is not supplied, so this is not a push-adjusted expected-value estimate.'
    return {'version':VERSION,'supported':valid,'win_condition':rule,'illustrative_outcomes':examples,
            'opportunity_logic':DRIVERS.get(category,'Expected workload × conversion/production rate. Evaluate this statistic against its own threshold.'),
            'projection_note':f'Central forecast: {projection:g}. A mean forecast is not a hit probability; the full outcome distribution matters.'if projection is not None else'No central statistic forecast supplied; none invented.',
            'price_comparison':price,'scope':'Exact-line arithmetic and explanatory scenarios, not a new prediction model or proof of profitability. Illustrations assume participation and final official stats; platform void/stat-correction rules can differ.'}


def cross_market_examples(rows,sport):
    """One coherent, explicitly hypothetical stat line per player/game."""
    groups={}
    for row in rows:groups.setdefault((row.get('Game'),row.get('Player')),[]).append(row)
    output={}
    for key,group in groups.items():
        categories={r.get('Category')for r in group}
        stats=None
        if sport=='NFL'and len(categories&{'Receptions','Receiving yards','Anytime touchdown'})>=2:
            stats={'Receptions':6,'Receiving yards':48,'Anytime touchdown':0}
        elif sport=='NBA'and len(categories&{'Points','Rebounds','Assists','PRA','Three-pointers made'})>=2:
            stats={'Points':20,'Rebounds':6,'Assists':4,'PRA':30,'Three-pointers made':2}
        if stats is None:continue
        examples=[];seen=set()
        for r in group:
            category=r.get('Category')
            if category not in stats:continue
            identity=(category,r.get('Selection'),str(r.get('Line')))
            if identity in seen:continue
            seen.add(identity)
            result=outcome(category,r.get('Selection'),r.get('Line'),stats[category])
            if result=='Unknown':continue
            examples.append({'Category':category,'Selection':r.get('Selection'),'Line':r.get('Line'),'Illustrative actual':stats[category],'Result':result})
        if len({x['Category']for x in examples})>=2:
            output[key]={'label':'Hypothetical teaching example — not this player’s forecast or a likely game script','stat_line':stats,'markets':examples,'correlation_note':'These markets share player/game outcomes; probabilities must not be multiplied as if independent. No joint hit probability has been estimated.'}
    return output


def apply(rows,sport):
    cross=cross_market_examples(rows,sport);output=[]
    for original in rows:
        row=dict(original);row['Market reasoning']=analysis(row)
        if (row.get('Game'),row.get('Player'))in cross:row['Market reasoning']['cross_market_example']=cross[row.get('Game'),row.get('Player')]
        output.append(row)
    return output


def render(reasoning):
    import streamlit as st
    st.write('**Exact market — how this selection wins or loses**')
    for key in ('win_condition','opportunity_logic','projection_note','price_comparison'):st.write(reasoning[key])
    if reasoning.get('illustrative_outcomes'):st.dataframe(reasoning['illustrative_outcomes'],hide_index=True,use_container_width=True)
    cross=reasoning.get('cross_market_example')
    if cross:
        st.caption(cross['label']);st.write(cross['stat_line']);st.dataframe(cross['markets'],hide_index=True,use_container_width=True);st.caption(cross['correlation_note'])
    st.caption(reasoning['scope'])
