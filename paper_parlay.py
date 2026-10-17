from automatic_reports import autosave_report, load_report
"""Paper-only parlay builder and downloadable hypothetical ticket history."""
import copy
import json
import math
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import streamlit as st

RESULTS = ['Pending','Win','Loss','Push','Void']

def decimal_odds(value):
    odds = float(value)
    if not math.isfinite(odds) or abs(odds)<100 or abs(odds)>100000:
        raise ValueError('Use American odds of -100 or lower, or +100 or higher.')
    return 1+odds/100 if odds>0 else 1+100/abs(odds)

def american_odds(decimal):
    if not math.isfinite(decimal) or decimal <= 1:
        raise ValueError('Combined decimal odds must exceed 1.')
    return (decimal-1)*100 if decimal>=2 else -100/(decimal-1)

def quote_is_fresh(leg, now=None):
    now=now or datetime.now(timezone.utc)
    try:
        start=datetime.fromisoformat(leg['starts'].replace('Z','+00:00'))
        if start<=now:return False
        if leg.get('source')=='Loaded sportsbook quote':
            updated=datetime.fromisoformat(leg['updated'].replace('Z','+00:00'))
            return 0 <= (now-updated).total_seconds() <= 900
        return True
    except (ValueError,TypeError,KeyError,AttributeError):return False

def validate_legs(legs):
    if not 2<=len(legs)<=12:raise ValueError('Choose between 2 and 12 legs.')
    books={leg['book'].strip().casefold() for leg in legs}
    if len(books)!=1:raise ValueError('A parlay must use prices from one sportsbook. Choose the same book for every leg.')
    identities=[(leg['game'].strip().casefold(),leg['selection'].strip().casefold()) for leg in legs]
    if len(set(identities))!=len(identities):raise ValueError('The same selection cannot be included twice.')
    for leg in legs:
        if not leg['game'].strip() or not leg['selection'].strip() or not leg['book'].strip():raise ValueError('Each leg needs a game, selection and sportsbook.')
        decimal_odds(leg['odds'])
    return any(count>1 for count in Counter(leg['game'].strip().casefold() for leg in legs).values())

def parlay_price(legs, combined_quote=None):
    same_game=validate_legs(legs)
    if combined_quote is not None:return decimal_odds(combined_quote),True
    if same_game:raise ValueError('Same-game legs need the sportsbook’s combined parlay odds. Individual odds cannot determine that price.')
    return math.prod(decimal_odds(leg['odds']) for leg in legs),False

def settle(ticket):
    legs=ticket['legs'];stake=ticket['stake']
    results=[leg['result'] for leg in legs]
    if 'Loss' in results:return {'status':'Loss','payout':0.0,'profit':-stake}
    if 'Pending' in results:return {'status':'Pending','payout':None,'profit':None}
    remaining=[leg for leg in legs if leg['result']=='Win']
    if not remaining:return {'status':'Refund','payout':stake,'profit':0.0}
    if len(remaining)==len(legs):decimal=ticket['decimal']
    elif ticket['quoted']:
        return {'status':'Needs revised sportsbook odds after push/void','payout':None,'profit':None}
    else:decimal=math.prod(decimal_odds(leg['odds']) for leg in remaining)
    payout=stake*decimal
    return {'status':'Win','payout':payout,'profit':payout-stake}

def available_quotes(state,sport):
    payloads=[]
    game=state.get('sportsbook_result')
    if game and game[0]==sport:payloads.extend(game[2]['data'])
    single=state.get('sportsbook_props_result')
    if single and single[0]==sport:payloads.append(single[4]['data'])
    batch=state.get('sportsbook_props_all_result')
    if batch and batch[0][0]==sport:payloads.extend(r['data'] for r in batch[1]['results'])
    quotes={}
    for event in payloads:
        if not isinstance(event,dict):continue
        for book in event.get('bookmakers',[]):
            for market in book.get('markets',[]):
                for outcome in market.get('outcomes',[]):
                    try:decimal_odds(outcome.get('price'))
                    except (ValueError,TypeError):continue
                    selection=' '.join(str(v) for v in [market['key'],outcome.get('description',''),outcome.get('name',''),outcome.get('point','')] if v!='')
                    leg={'game':event['away_team']+' at '+event['home_team'],'selection':selection,'book':book['title'],'odds':outcome['price'],'starts':event['commence_time'],'updated':market.get('last_update') or book.get('last_update'),'source':'Loaded sportsbook quote','result':'Pending'}
                    leg['market']=market['key']
                    leg['team']=outcome.get('name') if market['key']=='h2h' and len(market.get('outcomes',[]))==2 and outcome.get('name') in (event['home_team'],event['away_team']) else None
                    identity=(leg['game'],selection,leg['book'])
                    previous=quotes.get(identity)
                    if previous is None or str(leg['updated'] or '')>str(previous['updated'] or ''):quotes[identity]=leg
    return [leg for leg in quotes.values() if quote_is_fresh(leg)]

def build_team_parlay(choices, selected):
    if not 2 <= len(selected) <= 12:raise ValueError('Select between 2 and 12 teams.')
    legs=[copy.deepcopy(choices[value]) for value in selected]
    if len({leg['game'] for leg in legs}) != len(legs):raise ValueError('Choose only one team to win each game.')
    if not all(quote_is_fresh(leg) for leg in legs):raise ValueError('Refresh sportsbook lines; a selected price is stale or its game has started.')
    validate_legs(legs)
    return legs

def parse_history(raw):
    if len(raw)>250000:raise ValueError('Paper history file is too large.')
    payload=json.loads(raw)
    if payload.get('schema')!=1 or not isinstance(payload.get('tickets'),list) or len(payload['tickets'])>100:raise ValueError('Unrecognized paper history file.')
    tickets=payload['tickets'];seen=set()
    for ticket in tickets:
        if not isinstance(ticket['id'],str) or len(ticket['id'])>50 or ticket['id'] in seen:raise ValueError('Invalid or duplicate ticket ID.')
        seen.add(ticket['id'])
        if ticket['sport'] not in ('NFL','NBA') or type(ticket['quoted']) is not bool:raise ValueError('Invalid ticket metadata.')
        stake=float(ticket['stake']);price=float(ticket['decimal'])
        if not math.isfinite(stake) or not 0<stake<=100000 or not math.isfinite(price) or not 1<price<=1e40:raise ValueError('Invalid ticket amount or price.')
        recorded=datetime.fromisoformat(ticket['recorded'])
        if recorded.tzinfo is None or recorded>datetime.now(timezone.utc):raise ValueError('Invalid recorded time.')
        validate_legs(ticket['legs'])
        for leg in ticket['legs']:
            if leg['result'] not in RESULTS or any(not isinstance(leg[k],str) or len(leg[k])>500 for k in ('game','selection','book')):raise ValueError('Invalid ticket leg.')
            start=datetime.fromisoformat(leg['starts'].replace('Z','+00:00'))
            if start.tzinfo is None or start<=recorded:raise ValueError('Paper ticket must be recorded before each game starts.')
        if not ticket['quoted'] and not math.isclose(price,math.prod(decimal_odds(l['odds']) for l in ticket['legs']),rel_tol=1e-8):raise ValueError('Ticket price does not match its legs.')
        ticket['stake']=stake;ticket['decimal']=price
    return tickets

def render_paper_parlay(sport, selected_date=None):
    st.divider();st.header('🎯 Paper Parlay Builder')
    st.caption('Practice with hypothetical stakes. Select at least two legs; every leg must win. This builder calculates payouts, not the chance of winning or the strongest picks. No bets are placed.')
    state_key='paper_parlay_draft_'+sport
    legs=st.session_state.setdefault(state_key,[])
    quotes=available_quotes(st.session_state,sport)
    if selected_date is not None:
        quotes=[q for q in quotes if datetime.fromisoformat(q['starts'].replace('Z','+00:00')).astimezone(ZoneInfo('America/Los_Angeles')).date()==selected_date]
    if quotes:
        books=sorted({q['book'] for q in quotes})
        book=st.selectbox('Parlay sportsbook',books,key='paper_parlay_book_'+sport)
        team_quotes=[q for q in quotes if q['book']==book and q.get('team')]
        choices={q['game']+' | '+q['team']:q for q in team_quotes}
        if choices:
            selected=st.multiselect('Choose teams to win',list(choices),format_func=lambda value:f"{choices[value]['team']} ({choices[value]['odds']:+g}) — {choices[value]['game']}",key='paper_team_choices_'+sport,max_selections=12)
            if st.button('Build parlay from selected teams',key='paper_build_teams_'+sport,disabled=len(selected)<2):
                try:
                    legs=build_team_parlay(choices,selected)
                    st.session_state[state_key]=legs
                    st.success('Your team parlay is ready. Enter your paper stake below.')
                except ValueError as exc:st.warning(str(exc))
            st.caption('Pick one winner per game. Build replaces the current draft with your selected teams and fills in this sportsbook’s moneyline odds automatically.')
        else:st.info('No fresh team moneylines are loaded for this sportsbook. Load or refresh game lines in the sportsbook section.')
        with st.expander('Add a player prop, spread or total instead'):
            extra=[q for q in quotes if q['book']==book and not q.get('team')]
            if extra:
                games=sorted({q['game'] for q in extra})
                selected_game=st.selectbox('Prop/spread/total game',games,key='paper_parlay_game_'+sport)
                options=[q for q in extra if q['game']==selected_game]
                index=st.selectbox('Loaded selection',list(range(len(options))),format_func=lambda i:f"{options[i]['selection']} | {options[i]['odds']:+g}",key='paper_parlay_quote_'+sport)
                if st.button('Add loaded selection to parlay',key='paper_add_quote_'+sport):
                    if len(legs)>=12:st.warning('Maximum 12 legs.')
                    elif any(l['game']==options[index]['game'] and l['selection']==options[index]['selection'] for l in legs):st.warning('That selection is already in your parlay.')
                    else:legs.append(copy.deepcopy(options[index]))
            else:st.info('Load player props or game spreads/totals to see these selections.')
        st.caption('Only upcoming quotes updated within 15 minutes are offered. Load sportsbook lines/props below, then interact here to see them. This does not request more API credits. Listed selections are not automatically Watch picks.')
    else:st.info('Load / refresh sportsbook game lines in the section above. Then choose your sportsbook and select teams here.')
    if legs:
        st.dataframe([{'Leg':i+1,'Game':l['game'],'Selection':l['selection'],'Sportsbook':l['book'],'American odds':l['odds'],'Game starts UTC':l['starts']} for i,l in enumerate(legs)],hide_index=True,use_container_width=True)
        remove=st.selectbox('Leg to remove',list(range(len(legs))),format_func=lambda i:f"Leg {i+1}: {legs[i]['selection']}",key='paper_remove_leg_'+sport)
        if st.button('Remove selected leg',key='paper_remove_'+sport):legs.pop(remove);st.rerun()
        if st.button('Clear parlay',key='paper_clear_'+sport):legs.clear();st.rerun()
    stake=st.number_input('Hypothetical stake ($)',min_value=1.0,max_value=100000.0,value=10.0,step=1.0,key='paper_stake_'+sport)
    use_quote=st.checkbox('Use the sportsbook’s combined parlay odds',key='paper_combined_'+sport)
    combined=st.number_input('Combined parlay American odds',min_value=-100000,max_value=100000,value=300,step=1,key='paper_combined_price_'+sport) if use_quote else None
    try:
        price,quoted=parlay_price(legs,combined)
        american=american_odds(price)
        st.write(f'**Combined odds:** {american:+.0f} American / {price:.3f} decimal'+(' — sportsbook price entered by you' if quoted else ' — standard parlay estimate'))
        cols=st.columns(2)
        cols[0].metric('Potential profit if all legs win',f'${stake*(price-1):,.2f}')
        cols[1].metric('Total payout including your stake',f'${stake*price:,.2f}')
        st.caption('Use the sportsbook’s final combined quote for an exact payout. Same-game legs, promotions, rounding, pushes and voids can change the price. No model win probabilities are multiplied here.')
        fresh=all(quote_is_fresh(l) for l in legs)
        if not fresh:st.warning('Some legs have started or their loaded prices are stale. Refresh the prices and rebuild those legs before saving.')
        history=st.session_state.setdefault('paper_parlay_tickets',parse_history((load_report('kamikaze_picks_paper_parlays.json') or '{"schema":1,"tickets":[]}').encode()))
        if st.button('Save paper parlay before kickoff',disabled=not fresh or len(history)>=100,key='paper_save_'+sport):
            ticket={'id':uuid.uuid4().hex,'sport':sport,'recorded':datetime.now(timezone.utc).isoformat(),'stake':stake,'decimal':price,'quoted':quoted,'legs':copy.deepcopy(legs)}
            history.append(ticket);st.success('Paper ticket created. Automatic permanent saving runs below.')
    except ValueError as exc:st.info(str(exc))
    render_paper_history(sport)

def render_paper_history(sport):
    st.session_state.setdefault('paper_parlay_tickets',parse_history((load_report('kamikaze_picks_paper_parlays.json') or '{"schema":1,"tickets":[]}').encode()))
    st.subheader('Paper parlay history')
    uploaded=st.file_uploader('Restore downloaded paper parlay history',type=['json'],key='paper_history_upload_'+sport)
    if uploaded is not None and st.button('Import paper history',key='paper_import_'+sport):
        try:
            imported=parse_history(uploaded.getvalue())
            history=st.session_state.setdefault('paper_parlay_tickets',parse_history((load_report('kamikaze_picks_paper_parlays.json') or '{"schema":1,"tickets":[]}').encode()))
            existing={t['id'] for t in history}
            new=[t for t in imported if t['id'] not in existing]
            if len(history)+len(new)>100:raise ValueError('Maximum 100 saved paper tickets.')
            history.extend(new);st.success(f'Imported {len(new)} paper tickets. Existing tickets were preserved.')
        except (ValueError,TypeError,KeyError,AttributeError,OverflowError):st.warning('Could not import this paper history. Use a JSON downloaded from this builder.')
    history=st.session_state.get('paper_parlay_tickets',[])
    tickets=[t for t in history if t['sport']==sport]
    if tickets:
        index=st.selectbox('Paper ticket to review',list(range(len(tickets))),format_func=lambda i:f"{tickets[i]['recorded']} | {len(tickets[i]['legs'])} legs | ${tickets[i]['stake']:.2f}",key='paper_review_'+sport)
        ticket=tickets[index]
        for i,leg in enumerate(ticket['legs']):
            leg['result']=st.selectbox(f"Leg {i+1}: {leg['game']} — {leg['selection']}",RESULTS,index=RESULTS.index(leg['result']),key='paper_result_'+ticket['id']+'_'+str(i))
        result=settle(ticket)
        st.write('**Paper result:** '+result['status'])
        if result['payout'] is not None:st.write(f"**Paper payout:** ${result['payout']:,.2f} · **Paper profit/loss:** ${result['profit']:+,.2f}")
        rows=[]
        for item in tickets:
            graded=settle(item)
            rows.append({'Recorded UTC':item['recorded'],'Legs':len(item['legs']),'Stake ($)':item['stake'],'Result':graded['status'],'Paper profit/loss ($)':round(graded['profit'],2) if graded['profit'] is not None else None})
        st.dataframe(rows,hide_index=True,use_container_width=True)
    if history:autosave_report('Download paper parlay history',json.dumps({'schema':1,'tickets':history},indent=2),file_name='kamikaze_picks_paper_parlays.json',mime='application/json',key='paper_history_download_'+sport)
    st.caption('Manually grade each leg from official results and sportsbook settlement rules. This is an editable paper record, not verified betting evidence. Ticket history and grading changes save automatically when permanent storage is configured. Check any save warnings.')

