"""Reported sportsbook prices and optional The Odds API connection."""
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import requests
import streamlit as st
from nfl_prop_model import render_prop_research
from pick_history import publish_rows

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

def render_nba_paper_quotes(events,books,key_prefix):
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
    if shown:st.dataframe(shown,hide_index=True,use_container_width=True)
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
        messages={401:'API key not accepted. Check your key.',403:'This request is not available for this API key.',429:'Rate or usage limit reached. Check your provider account.'}
        error = OddsSourceError(messages.get(response.status_code,f'Odds source returned HTTP {response.status_code}. Check market coverage and your account.'))
        error.status_code = response.status_code
        raise error
    try:data=response.json()
    except ValueError:raise OddsSourceError('Odds source returned unreadable data.') from None
    if not isinstance(data,(dict,list)):raise OddsSourceError('Unexpected odds source data.')
    return {'data':data,'retrieved':datetime.now(timezone.utc).isoformat(),'remaining':response.headers.get('x-requests-remaining','Not supplied'),'cost':response.headers.get('x-requests-last','Not supplied')}

def load_all_prop_lines(api_key, sport, events, markets, now=None):
    now = now or datetime.now(timezone.utc)
    fetched, failures = [], []
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
        except OddsSourceError as exc:
            failures.append(game+': '+str(exc))
            if getattr(exc,'status_code',None) in (401,403,429):
                failures.append('Stopped remaining requests because the key, account access, or usage limit needs attention.')
                break
    latest = max(fetched,key=lambda r:r['retrieved']) if fetched else None
    return {'results':fetched,'failures':failures,'remaining':latest['remaining'] if latest else 'Not supplied','loaded':datetime.now(timezone.utc).isoformat()}

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

def moneyline_reviews(events,models,now=None,sport='NFL'):
    now=now or datetime.now(timezone.utc)
    rows=[]
    for event in events:
        if datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))<=now:continue
        model=models.get((event['home_team'],event['away_team']))
        if not model or not model['eligible'] or (sport=='NFL' and not model.get('injury_verified',False)):continue
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
                    if sport=='NFL':p=adjust_row(feedback,p,now)
                    odds=numeric(outcome['price']);decimal=1+odds/100 if odds>0 else 1+100/abs(odds)
                    ev=p*decimal-1
                    if ev<=0 or p-market_p<.05:continue
                    rows.append(dict(feedback,**{'Game':event['away_team']+' at '+event['home_team'],'Team to research':outcome['name'],'Sportsbook':book['title'],'Moneyline':odds_text(odds),'Model win %':round(p*100,1),'Break-even %':round(market_p*100,1),'Market win % without margin':round(market_p/sum(probs)*100,1),'Model minus break-even (pp)':round((p-market_p)*100,1),'Model history through':model['cutoff'],'Quote updated UTC':updated,'Estimated return per $1':round(ev,3)}))
    return sorted(rows,key=lambda row:row['Model minus break-even (pp)'],reverse=True)

def render_sportsbooks(sport,selected_date,scoreboard,model_loader):
    if sport not in SPORT_KEYS:return
    st.divider();st.header(f'{sport} Sportsbook Game Lines & Player Props')
    source=st.selectbox('Sportsbook data source',['ESPN reported lines (free)','Multiple sportsbooks & props — The Odds API'],key='sportsbook_source')
    if source.startswith('ESPN'):
        rows=espn_lines(scoreboard)
        st.caption('Source: ESPN sportsbook feed. Uses reported close quotes; the feed does not supply quote update times. These are not verified live prices. Refresh live data reloads the scoreboard.')
        if rows:st.dataframe(rows,hide_index=True,use_container_width=True)
        else:st.info(f'ESPN has no sportsbook prices for these {sport} games.')
        st.info('Select Multiple sportsbooks & props to compare books and load player props. That connection requires a data-provider API key.')
        return
    st.markdown('[Get your own key from The Odds API](https://the-odds-api.com/)')
    st.caption('Start with the free allowance. Loads consume provider credits; no paid plan is purchased by this app. Game lines request three markets; props load only for the game and categories you select. Responses are cached five minutes. Coverage differs by book and season.')
    key=st.text_input('The Odds API key',type='password',key='sportsbook_api_key',help='Enter it here privately. Do not post your key in chat or GitHub. It is sent to The Odds API to retrieve your data and stays in this app session.')
    if not key:return
    try:
        if st.button('Load / refresh sportsbook game lines',key='sportsbook_load'):
            odds_request.clear()
            result=odds_request(key,sport)
            st.session_state['sportsbook_result']=(sport,key,result)
        saved=st.session_state.get('sportsbook_result')
        if not saved or saved[:2]!=(sport,key):
            st.info('Click Load / refresh sportsbook game lines.');return
        result=saved[2]
        events=[event for event in result['data'] if pacific(event['commence_time']).date()==selected_date]
        st.caption(f"Retrieved {result['retrieved']}. Credits remaining at retrieval: {result['remaining']}. Last request cost: {result['cost']}. Displaying sidebar date in Pacific time.")
        if not events:st.info('No bookmaker events for the selected date. Choose a different sidebar date; preseason or distant dates may not be covered.');return
        names=sorted({book['title'] for event in events for book in event.get('bookmakers',[])})
        selected_books=st.multiselect('Compare sportsbooks',names,default=names,key='sportsbook_books')
        st.caption('Select multiple books for a broader price comparison. Only place or paper-record selections at the actual book and price you can use. More sportsbook prices do not provide bet counts or money volume.')
        if not selected_books:st.info('Select at least one sportsbook.');return
        filtered=[dict(event,bookmakers=[b for b in event.get('bookmakers',[]) if b['title'] in selected_books]) for event in events]
        st.dataframe(bookmaker_rows(filtered),hide_index=True,use_container_width=True)
        if sport=='NBA':render_nba_paper_quotes(filtered,selected_books,'nba_moneyline_paper')
        st.caption('Bookmaker names and quote timestamps come from the provider. Refresh before acting; displayed prices can change. Compare prices only for the same market, selection and line.')
        st.subheader('Player props and additional game markets')
        st.caption('Market prices are not recommendations. NFL yardage categories have experimental analysis; NBA props have no tested forecasting model yet. Spreads and totals are not modeled.')
        st.caption('Choose categories to load prices for your paper parlay. Attempts, touchdowns, team totals and other added markets are prices only; no tested pick model is available for them yet. Availability varies by sportsbook and game. Each selected category increases the potential request cost.')
        all_option = '__all_nfl_games__'
        event_id=st.selectbox('Player props game',[e['id'] for e in events]+[all_option],format_func=lambda value:f'All {sport} games on selected date' if value==all_option else next(e['away_team']+' at '+e['home_team'] for e in events if e['id']==value),key='sportsbook_props_game')
        labels=st.multiselect('Prop categories',list(PROP_MARKETS[sport]),default=list(PROP_MARKETS[sport])[:2],key='sportsbook_props_categories')
        markets=','.join(sorted(PROP_MARKETS[sport][label] for label in labels))
        if event_id == all_option:
            targets = [e for e in events if datetime.fromisoformat(e['commence_time'].replace('Z','+00:00')) > datetime.now(timezone.utc)]
            st.caption(f'All games: {len(targets)} upcoming {sport} games × {len(labels)} categories = up to {len(targets)*len(labels)} credits for a fresh load. Cached responses may cost no new credits. Started games are skipped. Analysis adds no sportsbook credits.')
            batch_key = (sport,key,str(selected_date),markets,tuple(e['id'] for e in targets))
            loaded_all = st.button('Load all games and analyze player props',key='sportsbook_props_all_load',disabled=not markets or not targets)
            if loaded_all and markets and targets:
                st.session_state.pop('sportsbook_props_all_result',None)
                with st.spinner(f'Loading selected prop categories for all upcoming {sport} games...'):
                    batch = load_all_prop_lines(key,sport,targets,markets)
                st.session_state['sportsbook_props_all_result'] = (batch_key,batch)
            all_saved = st.session_state.get('sportsbook_props_all_result')
            if all_saved and all_saved[0] == batch_key:
                batch = all_saved[1]
                for failure in batch['failures']:st.warning(failure)
                loaded_events = [r['data'] for r in batch['results']]
                st.caption(f"Loaded {len(loaded_events)} of {len(targets)} games. Most recent provider-reported credits remaining: {batch['remaining']}.")
                if loaded_events:
                    render_prop_market_board(loaded_events,selected_books,sport,'all_prop_board')
                    if sport=='NFL':render_prop_research(loaded_events,scoreboard,selected_books,batch['loaded'],auto_analyze=loaded_all)
                    else:render_nba_paper_quotes(loaded_events,selected_books,'nba_all_props_paper')
                    with st.expander('View all sportsbook prices — not recommendations'):
                        st.caption('Raw market quotes include both Over and Under. Use the analyzed shortlist above for an experimental paper direction or Pass.')
                        st.dataframe(bookmaker_rows(loaded_events,selected_books,True),hide_index=True,use_container_width=True)
                else:st.info('No prop data loaded. Check coverage and the warnings above.')
        else:
            if st.button('Load selected player prop lines',key='sportsbook_props_load') and markets:
                prop_result=odds_request(key,sport,event_id,markets)
                st.session_state['sportsbook_props_result']=(sport,key,event_id,markets,prop_result)
            prop_saved=st.session_state.get('sportsbook_props_result')
            if prop_saved and prop_saved[:4]==(sport,key,event_id,markets):
                props=bookmaker_rows([prop_saved[4]['data']],selected_books,True)
                if not props:st.info('No selected player props returned.')
                st.caption(f"Prop request credits remaining: {prop_saved[4]['remaining']}. Request cost: {prop_saved[4]['cost']}.")
                if props:
                    render_prop_market_board([prop_saved[4]['data']],selected_books,sport,'single_prop_board')
                    if sport=='NFL':render_prop_research(prop_saved[4]['data'],scoreboard,selected_books,prop_saved[4]['retrieved'])
                    else:render_nba_paper_quotes([prop_saved[4]['data']],selected_books,'nba_single_props_paper')
                    with st.expander('View all sportsbook prices — not recommendations'):
                        st.caption('Both sides are shown here as available bets, not picks. The analyzed shortlist is above.')
                        st.dataframe(props,hide_index=True,use_container_width=True)
        st.subheader(f'{sport} game shortlist — experimental moneylines')
        st.caption('Compares adjusted Elo with the break-even price; requires a gap of at least five percentage points, a quote no more than 15 minutes old, and regular-season model history no more than 30 days old. Current rosters and recent injury reports are checked for both teams. Unavailable or uncertain primary passers and major offensive usage players block picks. Elo has no validated numerical injury adjustment; defensive and offensive-line effects remain unmodeled.')
        if st.button('Compare model with current moneylines',key='sportsbook_research'):
            models=model_loader(sport,scoreboard)
            injury_notes=[{'Game':away+' at '+home,'Status':'Availability screen passed' if context.get('injury_verified') else 'PASS — injury verification failed','Reason':context.get('injury_reason'),'Verified UTC':context.get('injury_checked_utc')} for (home,away),context in models.items()] if sport=='NFL' else []
            st.session_state['moneyline_injury_notes']=injury_notes
            reviews=moneyline_reviews(filtered,models,sport=sport)
            st.session_state['moneyline_history_candidates']=(str(selected_date),tuple(selected_books),reviews,datetime.now(timezone.utc).isoformat(),sport)
        if st.session_state.get('moneyline_injury_notes'):
            with st.expander('Moneyline injury verification — both teams'):
                st.dataframe(st.session_state['moneyline_injury_notes'],hide_index=True,use_container_width=True)
        saved_reviews=st.session_state.get('moneyline_history_candidates')
        if saved_reviews and saved_reviews[:2]==(str(selected_date),tuple(selected_books)) and len(saved_reviews)>4 and saved_reviews[4]==sport and (sport!='NFL' or all(r.get('Injury verification passed') for r in saved_reviews[2])):
            reviews=saved_reviews[2]
            now=datetime.now(timezone.utc)
            if (now-datetime.fromisoformat(saved_reviews[3])).total_seconds()>900:reviews=[]
            reviews=[r for r in reviews if 0<=(now-datetime.fromisoformat(r['Quote updated UTC'].replace('Z','+00:00'))).total_seconds()<=900 and any(e['away_team']+' at '+e['home_team']==r['Game'] and datetime.fromisoformat(e['commence_time'].replace('Z','+00:00'))>now for e in filtered)]
            if reviews:
                unique={}
                for row in reviews:
                    identity=(row['Game'],row['Team to research'])
                    if identity not in unique or row['Estimated return per $1']>unique[identity]['Estimated return per $1']:unique[identity]=row
                reviews=list(unique.values())
                for row in reviews:
                    row['Decision'] = 'Watch — experimental'
                    row['Reason'] = 'Elo probability exceeds the quoted break-even price by at least five points and both teams passed current offensive availability checks. Injury effects, replacement quality and weather are not numerically modeled.' if sport=='NFL' else 'NBA Elo price comparison; no numerical injury adjustment.'
                st.dataframe(reviews,hide_index=True,use_container_width=True)
                records=[{'Decision':r['Decision'],'Category':'Moneyline','Game':r['Game'],'Player':r['Team to research'],'Selection':'Win','Line':None,'Odds':r['Moneyline'],'Estimated win %':r['Model win %'],'Sportsbook':r['Sportsbook'],'Quote updated UTC':r['Quote updated UTC'],'Model':r.get('Model','Adjusted NFL Elo moneyline'),'Base model':r.get('Base model','Adjusted NFL Elo moneyline'),'Raw estimated win %':r.get('Raw estimated win %'),'Feedback version':r.get('Feedback version'),'Feedback status':r.get('Feedback status'),'Reason':r.get('Reason','')+' Injury verification: '+str(r.get('Injury verification reason'))+'; checked '+str(r.get('Injury checked UTC'))} for r in reviews]
                publish_rows(records,filtered,key_prefix='moneyline_ledger',sport=sport)
            else:st.info('Pass — no eligible research candidates. The model may be stale, games may be preseason, quotes may be old, or no qualifying price gap exists.')
    except OddsSourceError as exc:
        st.warning(str(exc))
    except (requests.exceptions.RequestException,ValueError,KeyError,TypeError,AttributeError,OSError):
        st.warning('Sportsbook data could not be loaded. Check your API key, credits, market coverage and selected date. Your other app sections remain available.')
