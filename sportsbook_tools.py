from credit_saver import spending_allowed,choose_targets,balance_record
from probability_order import highest_probability
from team_emblems import render_team_table
"""Reported sportsbook prices and optional The Odds API connection."""
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import requests
import streamlit as st
from nfl_prop_model import render_prop_research
from pick_history import publish_rows
from odds_changes import estimated_credits, render_changes
from sportsbook_presets import STANDARD_PRESETS, NBA_EXTRA_MARKETS, archive_market_board, reconcile_prop_selection
from scoring_quote_merge import with_game_totals

class OddsSourceError(ValueError):
    pass

SPORT_KEYS = {'NFL':'americanfootball_nfl', 'NBA':'basketball_nba'}
PROP_MARKETS = {'NFL':{'Passing yards':'player_pass_yds','Rushing yards':'player_rush_yds','Receiving yards':'player_reception_yds','Receptions':'player_receptions'},'NBA':{'Points':'player_points','Rebounds':'player_rebounds','Assists':'player_assists','Three-pointers made':'player_threes'}}
PROP_MARKETS['NFL'].update({
    'Alternate passing yards — cushion comparison':'player_pass_yds_alternate',
    'Alternate receiving yards — cushion comparison':'player_reception_yds_alternate',
    'Passing attempts':'player_pass_attempts', 'Passing completions':'player_pass_completions',
    'Rushing attempts':'player_rush_attempts', 'Anytime touchdown scorer':'player_anytime_td',
    'Passing touchdowns':'player_pass_tds', 'Rushing touchdowns':'player_rush_tds',
    'Receiving touchdowns':'player_reception_tds', 'Passing interceptions':'player_pass_interceptions',
    'Passing + rushing yards':'player_pass_rush_yds', 'Rushing + receiving yards':'player_rush_reception_yds',
    'Longest completion':'player_pass_longest_completion', 'Longest rush':'player_rush_longest',
    'Longest reception':'player_reception_longest', 'Field goals':'player_field_goals',
    'Kicking points':'player_kicking_points', 'Sacks':'player_sacks',
    'Solo tackles':'player_solo_tackles', 'Tackles + assists':'player_tackles_assists',
    'Team total points':'team_totals', 'Alternate team totals':'alternate_team_totals',
    'Alternate spreads':'alternate_spreads', 'Alternate game totals':'alternate_totals',
    'First-half moneyline':'h2h_h1', 'First-half spread':'spreads_h1',
    'First-half game total':'totals_h1', 'First-half team totals':'team_totals_h1',
})
PROP_MARKETS['NBA'].update({'Steals':'player_steals','Blocks':'player_blocks'})
PROP_MARKETS['NBA'].update(NBA_EXTRA_MARKETS)

def render_nba_paper_quotes(events,books,key_prefix):
    from app_view import is_research
    if not is_research():return
    now=datetime.now(timezone.utc);rows=[]
    categories={v:k for k,v in PROP_MARKETS['NBA'].items()}
    for event in events:
        if datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))<=now:continue
        for row in bookmaker_rows([event],books,True):
            try:
                age=(now-datetime.fromisoformat(row['Quote updated UTC'].replace('Z','+00:00'))).total_seconds()
                if not 0<=age<=900:continue
            except (ValueError,TypeError,AttributeError):continue
            market=row['Market']
            if market not in categories and market!='h2h':continue
            rows.append(dict(row,Category=categories.get(market,'Moneyline'),Player=row['Selection'] if market=='h2h' else row['Player'],Selection='Win' if market=='h2h' else row['Selection'],Decision='Manual paper selection',**{'Estimated win %':None,'Model':'NBA market prices only — no prop forecast'}))
    st.caption('NBA quotes are available market choices, not model recommendations. Select paper picks to test; no forecast probability is invented. Moneyline implied probability in the prices table is the price’s break-even rate.')
    if not rows:st.info('No fresh supported NBA prices to save.');return
    choices=st.multiselect('NBA selections to paper-track',range(len(rows)),format_func=lambda i:f"{rows[i]['Game']} · {rows[i]['Player']} · {rows[i]['Category']} · {rows[i]['Selection']} {rows[i]['Line']} · {rows[i]['Sportsbook']} {rows[i]['Odds']}",key=key_prefix+'_choices')
    selected=[rows[i] for i in choices]
    identities=[(r['Game'],r['Player'],r['Category']) for r in selected]
    if len(identities)!=len(set(identities)):st.warning('Choose one line and direction per player/category/game.');return
    if selected:publish_rows(selected,events,key_prefix=key_prefix,sport='NBA',manual=True)

def numeric(value):
    try:
        number=float(value)
        return number if math.isfinite(number) else None
    except (TypeError,ValueError):return None

def prop_market_board(events,books,sport):
    labels={value:label for label,value in PROP_MARKETS[sport].items()}
    grouped={}
    for row in bookmaker_rows(events,books,True):
        if row['Market'] not in labels:continue
        participant=row['Player'] if row['Player']!='—' else row['Selection'] if row['Selection'] not in ('Over','Under') else 'Game total'
        identity=(row['Game'],participant,row['Market'],str(row['Line']))
        entry=grouped.setdefault(identity,{'Game':row['Game'],'Player/team':participant,
            'Category':labels[row['Market']],'Line':row['Line'],'Forecast status':
            'Experimental forecast — see analyzed shortlist' if sport=='NFL' and row['Market'] in ('player_pass_yds','player_rush_yds','player_reception_yds','player_receptions','player_pass_attempts','player_rush_attempts') else 'Market prices only — forecast not tested',
            'Over price':'—','Over book':'—','Under price':'—','Under book':'—','Other selection':'—'})
        side=row['Selection'];price=numeric(row['Odds'])
        if side in ('Over','Under') and price is not None:
            previous=numeric(entry[side+' price'])
            if previous is None or price>previous:
                entry[side+' price']=row['Odds'];entry[side+' book']=row['Sportsbook'];entry[side+' quote UTC']=row['Quote updated UTC']
        else:entry['Other selection']=row['Selection']+' '+str(row['Odds'])+' · '+row['Sportsbook']
    return list(grouped.values())

def render_prop_market_board(events,books,sport,key_prefix):
    st.subheader(f'{sport} player-prop market board')
    st.caption('One row per player/category/line, with Over and Under prices in separate columns. Best loaded price across selected books is a price comparison, not a recommended direction. Different thresholds remain separate. Check quote timestamps; prices can change.')
    rows=prop_market_board(events,books,sport)
    if not rows:st.info('No matching categories returned by the selected sportsbooks.');return
    categories=sorted({r['Category'] for r in rows})
    selected=st.multiselect('Market board categories',categories,default=categories,key=key_prefix+'_categories')
    shown=[r for r in rows if r['Category'] in selected]
    search=st.text_input('Find a player or team',key=key_prefix+'_search').strip().lower()
    if search:shown=[r for r in shown if search in r['Player/team'].lower() or search in r['Game'].lower()]
    if shown:render_team_table(shown,hide_index=True,use_container_width=True, sport=sport)
    else:st.info('No entries match these filters.')
    st.caption('Solo tackles and tackles + assists are different markets. Sacks may be credited in half-sacks. The odds imply a break-even rate, not a researched player probability. Rushing/receiving prices remain visible even when the forecast stays on Pass.')

def implied(odds):
    value=numeric(odds)
    if value is None or abs(value)<100:return None
    return 100/(value+100) if value>0 else abs(value)/(abs(value)+100)

def odds_text(value):
    number=numeric(value)
    return f'{number:+g}' if number is not None else 'Unavailable'

def pacific(value):
    return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(ZoneInfo('America/Los_Angeles'))

def espn_lines(scoreboard):
    rows=[]
    for event in scoreboard.get('events',[]):
        competition=event.get('competitions',[{}])[0]
        for quote in competition.get('odds') or []:
            provider=quote.get('provider',{}).get('displayName') or quote.get('provider',{}).get('name','Unknown')
            for key,label,sides in [('moneyline','Moneyline',('home','away')),('pointSpread','Spread',('home','away')),('total','Total',('over','under'))]:
                market=quote.get(key,{})
                for side in sides:
                    price=market.get(side,{}).get('close',{})
                    if not price:continue
                    rows.append({'Game':event.get('name'),'Sportsbook':provider,'Market':label,'Selection':side.title(),'Line':price.get('line','—'),'Odds':odds_text(price.get('odds')),'Quote timestamp':'Not supplied by ESPN','Quote type':'Reported close quote'})
    return rows

@st.cache_data(ttl=300)
def odds_request(api_key,sport,event_id='',markets='h2h,spreads,totals'):
    path=f'sports/{SPORT_KEYS[sport]}/events/{event_id}/odds' if event_id else f'sports/{SPORT_KEYS[sport]}/odds'
    try:
        response=requests.get('https://api.the-odds-api.com/v4/'+path,params={'apiKey':api_key,'regions':'us','markets':markets,'oddsFormat':'american','dateFormat':'iso'},timeout=20)
    except requests.exceptions.RequestException:
        raise OddsSourceError('The odds source did not respond. Try again later.') from None
    if response.status_code != 200:
        try:
            payload=response.json()
            code=str(payload.get('error_code') or payload.get('code') or '') if isinstance(payload,dict) else ''
        except ValueError:code=''
        remaining=response.headers.get('x-requests-remaining','Not supplied')
        messages={401:'Provider could not authorize the request. Check subscription status and remaining credits before changing your key.',403:'This request is not available for this API subscription.',429:'Provider rate limit reached. Wait before retrying.'}
        codes={'OUT_OF_USAGE_CREDITS':'The Odds API credits are exhausted. NFL and NBA share this quota. Wait for the quota reset or review your subscription; changing sport does not restore credits.',
               'INVALID_KEY':'The Odds API reports an invalid key. Check the key privately in app settings.',
               'MISSING_KEY':'No API key was supplied. Enter it privately in app settings.',
               'DEACTIVATED_KEY':'The Odds API reports this key is deactivated. Check subscription status.',
               'EXCEEDED_FREQ_LIMIT':'Requests were sent too quickly. Wait before retrying.'}
        message=codes.get(code,messages.get(response.status_code,f'Odds source returned HTTP {response.status_code}. Check market coverage and subscription access.'))
        if code not in ('INVALID_KEY','MISSING_KEY','DEACTIVATED_KEY') and numeric(remaining)==0:message=codes['OUT_OF_USAGE_CREDITS']
        error = OddsSourceError(message)
        error.status_code = response.status_code
        error.provider_code=code
        error.remaining=remaining
        raise error
    try:data=response.json()
    except ValueError:raise OddsSourceError('Odds source returned unreadable data.') from None
    if not isinstance(data,(dict,list)):raise OddsSourceError('Unexpected odds source data.')
    return {'data':data,'retrieved':datetime.now(timezone.utc).isoformat(),'remaining':response.headers.get('x-requests-remaining','Not supplied'),'cost':response.headers.get('x-requests-last','Not supplied')}

def load_all_prop_lines(api_key, sport, events, markets, now=None):
    now = now or datetime.now(timezone.utc)
    fetched, failures = [], []
    reported_remaining='Not supplied'
    for event in events:
        if datetime.fromisoformat(event['commence_time'].replace('Z','+00:00')) <= now:
            continue
        game = event['away_team']+' at '+event['home_team']
        try:
            result = odds_request(api_key,sport,event['id'],markets)
            data = result['data']
            if not isinstance(data,dict) or data.get('id') != event['id'] or (data.get('home_team'),data.get('away_team')) != (event['home_team'],event['away_team']):
                failures.append(game+': no matching prop data returned.')
                continue
            fetched.append(result)
            reported_remaining=result['remaining']
            if numeric(reported_remaining)==0:
                failures.append('All shared NFL/NBA odds credits have been used. Remaining games were skipped; already loaded prices remain visible.')
                break
        except OddsSourceError as exc:
            failures.append(game+': '+str(exc))
            if getattr(exc,'remaining','Not supplied')!='Not supplied':reported_remaining=exc.remaining
            if getattr(exc,'status_code',None) in (401,403,429) or getattr(exc,'provider_code',None)=='OUT_OF_USAGE_CREDITS':
                failures.append('Stopped remaining requests because the key, account access, or usage limit needs attention.')
                break
    latest = max(fetched,key=lambda r:r['retrieved']) if fetched else None
    return {'results':fetched,'failures':failures,'remaining':reported_remaining,'loaded':datetime.now(timezone.utc).isoformat()}

def bookmaker_rows(events,books=(),props=False):
    rows=[]
    for event in events:
        for book in event.get('bookmakers',[]):
            if books and book['title'] not in books:continue
            for market in book.get('markets',[]):
                for outcome in market.get('outcomes',[]):
                    odds=outcome.get('price');prob=implied(odds)
                    rows.append({'Game':event['away_team']+' at '+event['home_team'],'Sportsbook':book['title'],'Market':market['key'],'Player':outcome.get('description','—'),'Selection':outcome.get('name','—'),'Line':outcome.get('point','—'),'Odds':odds_text(odds),'Implied %':round(prob*100,1) if prob is not None else None,'Quote updated UTC':market.get('last_update') or book.get('last_update','Unavailable')})
    return rows

def moneyline_reviews(events,models,now=None,sport='NFL',include_passes=False):
    now=now or datetime.now(timezone.utc)
    rows=[]
    for event in events:
        if datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))<=now:continue
        model=models.get((event['home_team'],event['away_team']))
        if not model or not model['eligible']:continue
        for book in event.get('bookmakers',[]):
            for market in book.get('markets',[]):
                if market['key']!='h2h' or len(market.get('outcomes',[]))!=2:continue
                if {o.get('name') for o in market['outcomes']} != {event['home_team'],event['away_team']}:continue
                updated=market.get('last_update') or book.get('last_update')
                try:age=(now-datetime.fromisoformat(updated.replace('Z','+00:00'))).total_seconds()
                except (ValueError,TypeError,AttributeError):continue
                if age<0 or age>900:continue
                probs=[implied(outcome.get('price')) for outcome in market['outcomes']]
                if any(p is None for p in probs):continue
                for outcome,market_p in zip(market['outcomes'],probs):
                    if outcome['name'] not in (event['home_team'],event['away_team']):continue
                    p=model['probability'] if outcome['name']==event['home_team'] else 1-model['probability']
                    from pick_learning import adjust_row
                    feedback={'Model':'Adjusted NFL Elo moneyline' if sport=='NFL' else 'Adjusted NBA Elo moneyline','Category':'Moneyline','Selection':'Win','Injury verification passed':sport=='NFL' and model.get('injury_verified',False),'Injury verification reason':model.get('injury_reason'),'Injury checked UTC':model.get('injury_checked_utc')}
                    from online_learning import adjust_probability
                    feedback['Base model']=feedback['Model']
                    online_p=adjust_probability(feedback,p,now,sport=sport)
                    if feedback.get('Online version'):
                        feedback['Raw estimated win %']=100*p
                        feedback['Feedback status']=feedback['Online learning status']
                        p=online_p
                    else:p=adjust_row(feedback,p,now,sport=sport)
                    odds=numeric(outcome['price']);decimal=1+odds/100 if odds>0 else 1+100/abs(odds)
                    ev=p*decimal-1
                    qualifies=ev>0 and p-market_p>=.05
                    if not qualifies and not include_passes:continue
                    feedback['Validation']=model.get('validation',{})
                    feedback['History source']=model.get('history_basis','Historical regular-season team results')
                    rows.append(dict(feedback,Player=outcome['name'],Selection='Win',Category='Moneyline',Line=None,Odds=odds,Decision='Watch — experimental' if qualifies else 'Pass',**{'Estimated win %':round(p*100,1),'Game':event['away_team']+' at '+event['home_team'],'Team to research':outcome['name'],'Sportsbook':book['title'],'Moneyline':odds_text(odds),'Model win %':round(p*100,1),'Break-even %':round(market_p*100,1),'Market win % without margin':round(market_p/sum(probs)*100,1),'Model minus break-even (pp)':round((p-market_p)*100,1),'Model history through':model['cutoff'],'Quote updated UTC':updated,'Estimated return per $1':round(ev,3)}))
    return sorted(rows,key=lambda row:row['Model minus break-even (pp)'],reverse=True)


def render_moneyline_shortlist(sport,filtered,scoreboard,model_loader,selected_date,selected_books,use_preset=False):
    st.subheader(f'{sport} moneyline predictions — game winners')
    st.caption('Compares adjusted Elo with the break-even price; requires a gap of at least five percentage points, quotes no more than 15 minutes old, and recent regular-season history (NBA opening dates can use a labeled prior-season rating). '+('NFL roster and injury checks are warnings only; injury, defensive and offensive-line effects are not numerically modeled.' if sport=='NFL' else 'NBA preseason games do not qualify for this regular-season model. NBA supported props use a separate experimental minutes-rate forecast; unsupported categories remain prices only. NBA injury effects are not numerically modeled.'))
    signature=(sport,str(selected_date),tuple(selected_books),tuple((e.get('id'),m.get('last_update') or b.get('last_update'))for e in filtered for b in e.get('bookmakers',[])for m in b.get('markets',[])if m.get('key')=='h2h'))
    auto_compare=sport=='NBA' and bool(signature[-1]) and st.session_state.get('moneyline_auto_signature')!=signature
    if st.button('Compare model with current moneylines',key='sportsbook_research') or use_preset or auto_compare:
        try:models=model_loader(sport,scoreboard)
        except Exception:
            st.info('Moneyline history is temporarily unavailable. Player-prop research remains available; retry the comparison without loading new odds.')
            return
        st.session_state['moneyline_auto_signature']=signature
        injury_notes=[{'Game':away+' at '+home,'Status':'Availability screen passed' if context.get('injury_verified') else 'Injury warning — not numerically adjusted','Reason':context.get('injury_reason'),'Verified UTC':context.get('injury_checked_utc')} for (home,away),context in models.items()] if sport=='NFL' else []
        st.session_state['moneyline_injury_notes']=injury_notes
        analyzed=moneyline_reviews(filtered,models,sport=sport,include_passes=True)
        from game_day_diagnostics import apply as apply_game_day_diagnostic
        analyzed=apply_game_day_diagnostic(analyzed,sport)
        from forecast_tracking import archive as archive_forecasts
        archive_forecasts(analyzed,filtered,scoreboard,sport)
        reviews=[r for r in analyzed if r['Decision']!='Pass']
        st.session_state['moneyline_history_candidates']=(str(selected_date),tuple(selected_books),reviews,datetime.now(timezone.utc).isoformat(),sport)
    if st.session_state.get('moneyline_injury_notes'):
        with st.expander('Moneyline injury verification — both teams'):
            render_team_table(st.session_state['moneyline_injury_notes'],hide_index=True,use_container_width=True, sport=sport)
    saved_reviews=st.session_state.get('moneyline_history_candidates')
    if saved_reviews and saved_reviews[:2]==(str(selected_date),tuple(selected_books)) and len(saved_reviews)>4 and saved_reviews[4]==sport:
        reviews=saved_reviews[2]
        now=datetime.now(timezone.utc)
        if (now-datetime.fromisoformat(saved_reviews[3])).total_seconds()>900:reviews=[]
        reviews=[r for r in reviews if 0<=(now-datetime.fromisoformat(r['Quote updated UTC'].replace('Z','+00:00'))).total_seconds()<=900 and any(e['away_team']+' at '+e['home_team']==r['Game'] and datetime.fromisoformat(e['commence_time'].replace('Z','+00:00'))>now for e in filtered)]
        if reviews:
            unique={}
            for row in reviews:
                identity=(row['Game'],row['Team to research'])
                if identity not in unique or row['Estimated return per $1']>unique[identity]['Estimated return per $1']:unique[identity]=row
            reviews=highest_probability(list(unique.values()),"Model win %")
            for row in reviews:
                row['Decision'] = 'Watch — experimental'
                row['Reason'] = 'Historical Elo exceeds the quoted break-even price by at least five points. Injury warnings do not block this candidate; injury effects, replacement quality and weather are not numerically modeled.' if sport=='NFL' else 'NBA Elo price comparison; no numerical injury adjustment.'
            st.caption("Sorted by estimated win probability, highest first. Probability and payout value are different measures.")
            render_team_table(reviews,hide_index=True,use_container_width=True, sport=sport)
            records=[{**{k:r[k] for k in ('Base estimated win %','Online input win %','Online version','Online learning status','Candidate win %','Game-day diagnostic','Validation','Homework','Probability tier','Probability evidence','Selection policy','Market reasoning') if k in r},'Decision':r['Decision'],'Category':'Moneyline','Game':r['Game'],'Player':r['Team to research'],'Selection':'Win','Line':None,'Odds':r['Moneyline'],'Estimated win %':r['Model win %'],'Sportsbook':r['Sportsbook'],'Quote updated UTC':r['Quote updated UTC'],'Model':r.get('Model','Adjusted NFL Elo moneyline'),'Base model':r.get('Base model','Adjusted NFL Elo moneyline'),'Raw estimated win %':r.get('Raw estimated win %'),'Feedback version':r.get('Feedback version'),'Feedback status':r.get('Feedback status'),'Reason':r.get('Reason','')+' Injury verification: '+str(r.get('Injury verification reason'))+'; checked '+str(r.get('Injury checked UTC'))} for r in reviews]
            from saved_pick_explanation import render_current_explanations
            render_current_explanations(records,sport+'_moneyline_current')
            publish_rows(records,filtered,key_prefix='moneyline_ledger',sport=sport)
        else:st.info('Pass — no eligible research candidates. The model may be stale, games may be preseason, quotes may be old, or no qualifying price gap exists.')

def render_sportsbooks(sport,selected_date,scoreboard,model_loader):
    if sport not in SPORT_KEYS:return
    st.divider();st.header(f'{sport} Sportsbook Game Lines & Player Props')
    source=st.selectbox('Sportsbook data source',['ESPN reported lines (free)','Multiple sportsbooks & props — The Odds API'],key='sportsbook_source')
    if source.startswith('ESPN'):
        rows=espn_lines(scoreboard)
        st.caption('Source: ESPN sportsbook feed. Uses reported close quotes; the feed does not supply quote update times. These are not verified live prices. Refresh live data reloads the scoreboard.')
        if rows:render_team_table(rows,hide_index=True,use_container_width=True, sport=sport)
        else:st.info(f'ESPN has no sportsbook prices for these {sport} games.')
        st.info('Select Multiple sportsbooks & props to compare books and load player props. That connection requires a data-provider API key.')
        return
    st.markdown('[Get your own key from The Odds API](https://the-odds-api.com/)')
    st.caption('Start with the free allowance. Loads consume provider credits; no paid plan is purchased by this app. Game lines request three markets; props load only for the game and categories you select. Responses are cached five minutes. Coverage differs by book and season.')
    key=st.text_input('The Odds API key',type='password',key='sportsbook_api_key',help='Enter it here privately. Do not post your key in chat or GitHub. It is sent to The Odds API to retrieve your data and stays in this app session.')
    if not key:return
    mode=st.radio('Odds credit mode',['Credit-saving mode','Saved data only — 0 credits','Standard mode'],key='odds_credit_mode',horizontal=True)
    budget=int(st.number_input('Maximum credits per click',min_value=1,max_value=500,value=10,step=1,key='odds_click_budget')) if mode=='Credit-saving mode' else 500
    existing=st.session_state.get('sportsbook_result')
    remaining=existing[2].get('remaining') if existing and existing[:2]==(sport,key) else None
    quota=st.session_state.get('odds_quota_check')
    import hashlib
    fingerprint=hashlib.sha256(key.encode()).hexdigest()
    if quota and quota['key_hash']==fingerprint:remaining=quota['remaining']
    if st.button('Check remaining credits — 0 credits',key='odds_check_quota'):
        try:
            response=requests.get('https://api.the-odds-api.com/v4/sports/',params={'apiKey':key},timeout=15)
            response.raise_for_status()
            remaining=response.headers.get('x-requests-remaining')
            st.session_state['odds_quota_check']=balance_record(st.session_state.get('odds_quota_check'),fingerprint,remaining,datetime.now(timezone.utc).isoformat())
        except (requests.exceptions.RequestException,ValueError):st.warning('The free balance check failed. No new odds were requested; check your provider dashboard.')
    st.caption('Last reported credits remaining: '+str(remaining if remaining is not None else 'Unknown')+'. Cached prices may be outdated. Budget checks assume a fresh request; an available cache hit may cost 0.')
    allow_game,game_reason=spending_allowed(mode,3,budget,remaining)
    st.caption('Credit-saving mode: choose a few games and categories below. Full-slate preset buttons are available in Standard mode. Saved-data mode blocks new odds loads while keeping already loaded prices visible.')
    automatic=False  # Background workflow owns autoload; no session-planner import.
    st.caption('Background preset preparation now runs in GitHub Actions while the app is closed. See Background research for status and its shared eight-credit daily automated budget. This page does not automatically spend credits on each new session. Load buttons and add-ons below are explicit extra requests outside that background budget.')
    try:
        quick_nfl=False
        quick_nba=False
        if sport=='NFL':
            st.caption('Standard NFL slate: moneylines + game totals, passing yards, rushing yards, anytime touchdowns and receiving yards. Fresh budget: up to 3 game-line credits plus 4 credits per upcoming game. Saved recommendations are frozen automatically; unsupported markets remain prices/research only.')
            quick_nfl=st.button('Load NFL slate, analyze & autosave — up to 3 + 4/game credits',key='quick_nfl_slate',disabled=mode!='Standard mode' or not allow_game)
            with st.expander('About team sack estimates'):
                st.write('Team defensive sacks: the provider lists individual-player sacks, not a confirmed team sack-total market. The Team statistics tab now provides a free sack-pressure/pass-protection research comparison. It is not yet a validated sack betting model.')
        if sport=='NBA':
            st.caption('NBA preset: moneylines, points, assists, rebounds, PRA and three-pointers made. Fresh budget: up to 3 credits for game lines plus 5 per upcoming game. PRA uses an experimental combined-stat forecast with its own historical baseline gate.')
            quick_nba=st.button('Load NBA slate & save board — up to 3 + 5/game credits',key='quick_nba_slate',disabled=mode!='Standard mode' or not allow_game)
            st.caption('Shooting categories are made shots unless explicitly labeled attempted. Field-goal attempts and three-point attempts are not included as unsupported market keys.')
        quick_load=quick_nfl or quick_nba or automatic
        st.caption('Fresh game-line load: up to 3 credits (moneyline, spread and total; one US region). Viewing saved results costs 0 credits.')
        if st.button('Load / refresh sportsbook game lines — up to 3 credits',key='sportsbook_load',disabled=not allow_game) or quick_load:
            if not quick_load:odds_request.clear(key,sport)
            result=odds_request(key,sport)
            st.session_state['sportsbook_result']=(sport,key,result)
            remaining=result.get('remaining')
            st.session_state['odds_quota_check']=balance_record(st.session_state.get('odds_quota_check'),fingerprint,remaining,result['retrieved'])
            remaining=st.session_state['odds_quota_check']['remaining'] if st.session_state.get('odds_quota_check') else remaining
        saved=st.session_state.get('sportsbook_result')
        if not saved or saved[:2]!=(sport,key):
            st.info('Load game lines once when credits are available. Saved predictions and ESPN live tracking remain available elsewhere on the dashboard without odds credits.');return
        result=saved[2]
        events=[event for event in result['data'] if pacific(event['commence_time']).date()==selected_date]
        st.caption(f"Retrieved {result['retrieved']}. Credits remaining at retrieval: {result['remaining']}. Last request cost: {result['cost']}. Displaying sidebar date in Pacific time.")
        if not events:st.info('No bookmaker events for the selected date. Choose a different sidebar date; preseason or distant dates may not be covered.');return
        names=sorted({book['title'] for event in events for book in event.get('bookmakers',[])})
        selected_books=st.multiselect('Compare sportsbooks',names,default=names,key='sportsbook_books_'+sport)
        st.caption('Select multiple books for a broader price comparison. Only place or paper-record selections at the actual book and price you can use. More sportsbook prices do not provide bet counts or money volume.')
        if not selected_books:st.info('Select at least one sportsbook.');return
        filtered=[dict(event,bookmakers=[b for b in event.get('bookmakers',[]) if b['title'] in selected_books]) for event in events]
        with st.expander('View sportsbook game prices'):
            render_team_table(bookmaker_rows(filtered),hide_index=True,use_container_width=True, sport=sport)
        # Load and analyze props before the independent moneyline history work.
        if sport=='NBA':
            with st.expander('Optional manual NBA paper selections'):
                render_nba_paper_quotes(filtered,selected_books,'nba_moneyline_paper')
        st.caption('Bookmaker names and quote timestamps come from the provider. Refresh before acting; displayed prices can change. Compare prices only for the same market, selection and line.')
        st.subheader('Player props and additional game markets')
        st.caption('Market prices are not recommendations. NFL yardage categories have experimental analysis; NBA points, rebounds, assists, threes and PRA have an experimental minutes-rate forecast with a chronological baseline gate. NFL anytime touchdowns and game totals have separate scoring models; spreads remain prices only.')
        st.caption('NFL passing/rushing/receiving yards, receptions and attempts have experimental analysis. Sacks and other unsupported markets show prices only. Each requested category can consume credits per game. Viewing cached results and rerunning analysis do not fetch new prices.')
        render_changes(filtered,sport+'_game_lines',result['retrieved'])
        upcoming_count=sum(datetime.fromisoformat(e['commence_time'].replace('Z','+00:00'))>datetime.now(timezone.utc) for e in events)
        preset_labels=STANDARD_PRESETS[sport]
        compact_labels=['Passing yards','Rushing yards'] if sport=='NFL' else ['Points','Rebounds']
        use_preset=quick_load
        if use_preset:
            st.session_state['sportsbook_props_game_'+sport]='__all_nfl_games__'
            st.session_state['sportsbook_props_categories_'+sport]=preset_labels
        fresh_props=st.checkbox('Request fresh prop prices on next load (may spend credits)',value=False,key='force_fresh_props')
        st.caption('Unchecked: reuse the five-minute provider-response cache when available. Checked: next Load requests new prices. No free check can establish whether sportsbook lines changed; the snapshot comparison below only compares prices already loaded.')
        all_option = '__all_nfl_games__'
        multiple_option='__multiple_prop_games__'
        reconcile_prop_selection(st.session_state,sport,[e['id'] for e in events],list(PROP_MARKETS[sport]))
        event_id=st.selectbox('Player props games',[e['id'] for e in events]+[all_option,multiple_option],index=len(events)+1,format_func=lambda value:'Choose multiple games' if value==multiple_option else f'All {sport} games on selected date' if value==all_option else next(e['away_team']+' at '+e['home_team'] for e in events if e['id']==value),key='sportsbook_props_game_'+sport)
        if st.button('Add on markets / customize',key='preset_add_on_'+sport):
            st.session_state['preset_add_on_open_'+sport]=True
        if st.session_state.get('preset_add_on_open_'+sport):
            labels=st.multiselect('Prop categories',list(PROP_MARKETS[sport]),default=preset_labels,key='sportsbook_props_categories_'+sport)
        else:
            labels=preset_labels
            st.caption('Permanent prop rotation: '+', '.join(labels)+'. Moneyline and game totals are loaded with game lines.')
        markets=','.join(sorted(PROP_MARKETS[sport][label] for label in labels))
        upcoming=[e for e in events if datetime.fromisoformat(e['commence_time'].replace('Z','+00:00'))>datetime.now(timezone.utc)]
        selected_ids=[e['id'] for e in events]
        if event_id==multiple_option or (mode=='Credit-saving mode' and event_id==all_option):
            selected_ids=st.multiselect('Games to load — only these games consume credits',[e['id'] for e in events],default=[e['id'] for e in upcoming[:1]],format_func=lambda value:next(e['away_team']+' at '+e['home_team'] for e in events if e['id']==value),key='credit_saver_games_'+sport)
        if automatic:selected_ids=selected_ids[:plan['max_games']]
        preview_games=sum(e['id'] in selected_ids for e in upcoming) if event_id in (all_option,multiple_option) else int(any(e['id']==event_id for e in upcoming))
        cost=estimated_credits(preview_games,markets)
        allowed,blocked_reason=spending_allowed(mode,cost,budget,remaining)
        st.caption(f'This prop load: up to {cost} credits for {preview_games} games × {len(labels)} categories. Viewing the current board costs 0.')
        if not allowed:st.info(blocked_reason)
        if st.button('Preview prop credit cost — 0 credits',key='preview_prop_cost'):
            st.info(f'Fresh-request budget: up to {estimated_credits(preview_games,markets)} credits = {preview_games} games × {len(labels)} categories × 1 US region. Cache hits can cost 0; unavailable markets may reduce cost. The API response headers report the actual request cost. No API request was made by this preview.')
        if event_id in (all_option,multiple_option):
            targets = choose_targets(events,selected_ids,datetime.now(timezone.utc))
            st.caption(f'Selected games: {len(targets)} upcoming {sport} games × {len(labels)} categories = up to {len(targets)*len(labels)} credits for a fresh load. Cached responses may cost no new credits. Started games are skipped. Analysis adds no sportsbook credits.')
            batch_key = (sport,key,str(selected_date),markets,tuple(e['id'] for e in targets))
            action_label='Load selected games & analyze' if sport=='NFL' else 'Load selected game markets'
            loaded_all = st.button(f'{action_label} — up to {estimated_credits(len(targets),markets)} credits',key='sportsbook_props_all_load',disabled=not markets or not targets or not allowed) or use_preset
            if loaded_all and not allowed:
                st.warning(blocked_reason)
                loaded_all=False
            if loaded_all and numeric(remaining)==0:
                st.warning('The game-line response reports zero credits remaining. Prop requests were skipped; already loaded data remains available.')
                loaded_all=False
            if loaded_all and markets and targets:
                if fresh_props:
                    for target in targets:odds_request.clear(key,sport,target['id'],markets)
                with st.spinner(f'Loading prop categories for the selected {sport} games...'):
                    batch = load_all_prop_lines(key,sport,targets,markets)
                st.session_state['sportsbook_props_all_result'] = (batch_key,batch)
                st.session_state['odds_quota_check']=balance_record(st.session_state.get('odds_quota_check'),fingerprint,batch.get('remaining'),batch['loaded'])
            all_saved = st.session_state.get('sportsbook_props_all_result')
            if all_saved and all_saved[0][:4] == batch_key[:4]:
                batch = all_saved[1]
                for failure in batch['failures']:st.warning(failure)
                loaded_events = [r['data'] for r in batch['results'] if r['data']['id'] in selected_ids]
                if sport=='NFL':
                    from scoring_quote_merge import with_game_totals
                    loaded_events=with_game_totals(loaded_events,filtered)
                st.caption(f"Displaying {len(loaded_events)} saved game snapshots. Most recent provider-reported credits remaining: {batch['remaining']}.")
                if loaded_events:
                    if sport=='NBA':archive_market_board(loaded_events,batch['loaded'],sport)
                    render_changes(loaded_events,sport+'_all_props',batch['loaded'])
                    render_prop_market_board(loaded_events,selected_books,sport,'all_prop_board')
                    if sport=='NFL':render_prop_research(loaded_events,scoreboard,selected_books,batch['loaded'],auto_analyze=loaded_all)
                    else:
                        from nba_prop_model import render as render_nba_props
                        render_nba_props(loaded_events,scoreboard,selected_books,auto_analyze=loaded_all,key_prefix='nba_all_props')
                        render_nba_paper_quotes(loaded_events,selected_books,'nba_all_props_paper')
                    with st.expander('View all sportsbook prices — not recommendations'):
                        st.caption('Raw market quotes include both Over and Under. Use the analyzed shortlist above for an experimental paper direction or Pass.')
                        render_team_table(bookmaker_rows(loaded_events,selected_books,True),hide_index=True,use_container_width=True, sport=sport)
                else:st.info('No prop data loaded. Check coverage and the warnings above.')
        else:
            action_label='Load selected props & analyze' if sport=='NFL' else 'Load selected prop markets'
            single_loaded=st.button(f'{action_label} — up to {estimated_credits(1,markets)} credits',key='sportsbook_props_load',disabled=not markets or not preview_games or not allowed)
            if single_loaded and markets and allowed:
                if fresh_props:odds_request.clear(key,sport,event_id,markets)
                prop_result=odds_request(key,sport,event_id,markets)
                st.session_state['sportsbook_props_result']=(sport,key,event_id,markets,prop_result)
                st.session_state['odds_quota_check']=balance_record(st.session_state.get('odds_quota_check'),fingerprint,prop_result.get('remaining'),prop_result['retrieved'])
            prop_saved=st.session_state.get('sportsbook_props_result')
            if prop_saved and prop_saved[:4]==(sport,key,event_id,markets):
                if sport=='NBA':archive_market_board([prop_saved[4]['data']],prop_saved[4]['retrieved'],sport)
                render_changes([prop_saved[4]['data']],sport+'_single_props_'+event_id,prop_saved[4]['retrieved'])
                props=bookmaker_rows([prop_saved[4]['data']],selected_books,True)
                if not props:st.info('No selected player props returned.')
                st.caption(f"Prop request credits remaining: {prop_saved[4]['remaining']}. Request cost: {prop_saved[4]['cost']}.")
                if props:
                    render_prop_market_board([prop_saved[4]['data']],selected_books,sport,'single_prop_board')
                    if sport=='NFL':
                        from scoring_quote_merge import with_game_totals
                        merged=with_game_totals([prop_saved[4]['data']],filtered)[0]
                        render_prop_research(merged,scoreboard,selected_books,prop_saved[4]['retrieved'],auto_analyze=single_loaded)
                    else:
                        from nba_prop_model import render as render_nba_props
                        render_nba_props([prop_saved[4]['data']],scoreboard,selected_books,auto_analyze=single_loaded,key_prefix='nba_single_props')
                        render_nba_paper_quotes([prop_saved[4]['data']],selected_books,'nba_single_props_paper')
                    with st.expander('View all sportsbook prices — not recommendations'):
                        st.caption('Both sides are shown here as available bets, not picks. The analyzed shortlist is above.')
                        render_team_table(props,hide_index=True,use_container_width=True, sport=sport)
        render_moneyline_shortlist(sport,filtered,scoreboard,model_loader,selected_date,selected_books,quick_load)
        if sport=='NFL':
            if use_preset:st.session_state['quick_team_sacks_loaded']=True
            if st.session_state.get('quick_team_sacks_loaded'):
                from pass_protection import render_pass_protection
                with st.expander('Team sack estimates — defense vs opposing pass protection',expanded=False):
                    render_pass_protection(selected_date.year,selected_date,auto_load=False,prefix='slate')
    except OddsSourceError as exc:
        st.warning(str(exc))
    except (requests.exceptions.RequestException,ValueError,KeyError,TypeError,AttributeError,OSError):
        st.warning('Sportsbook data could not be loaded. Check your API key, credits, market coverage and selected date. Your other app sections remain available.')

