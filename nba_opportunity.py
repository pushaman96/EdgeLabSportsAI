"""NBA minutes, shot-volume and conversion candidate using strictly earlier appearances."""
import math
import statistics
from nba_season_prior import season_year

VERSION = 'NBA minutes-shot-opportunities v1 / chronological benchmark'
VARIANTS=('median-minutes','incumbent-minutes','robust-rates')


def valid(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0


def estimate(history, year, team, cutoff, variant='median-minutes'):
    before=sorted((r for r in history if r['date']<str(cutoff) and valid(r.get('minutes')) and r['minutes']>0),key=lambda r:(r['date'],r['game']))
    prior=[r for r in before if season_year(r)==year-1]
    season=[r for r in before if season_year(r)==year]
    last_other=max((r['date']for r in season if r['team']!=team),default='')
    current=[r for r in season if r['team']==team and r['date']>last_other]
    if len(prior)<8 or ((prior[-1]['team']!=team or last_other) and len(current)<3):
        return None
    current_count=len(current);current=current[-12:]
    weight=current_count/(current_count+(4. if variant=='median-minutes'else 8.))
    # Median resists isolated early exits. The later-game benchmark decides
    # whether this change is useful; an injured appearance is not deleted.
    prior_minutes=statistics.median(r['minutes']for r in prior)if variant=='median-minutes'else statistics.mean(r['minutes']for r in prior)
    recent_minutes=(statistics.median(r['minutes']for r in current[-5:])if variant=='median-minutes'else statistics.mean(r['minutes']for r in current))if current else prior_minutes
    minutes=max(1.,min(40.,(1-weight)*prior_minutes+weight*recent_minutes))
    def rate(field):
        p=[r for r in prior if valid(r.get(field))]
        c=[r for r in current if valid(r.get(field))]
        if len(p)<8 or (current and len(c)!=len(current)):
            return None
        w=current_count/(current_count+8.)
        if variant=='robust-rates':
            pr=statistics.median(r[field]/r['minutes']for r in p)
            cr=statistics.median(r[field]/r['minutes']for r in c)if c else pr
        else:
            pr=sum(r[field]for r in p)/sum(r['minutes']for r in p)
            cr=sum(r[field]for r in c)/sum(r['minutes']for r in c)if c else pr
        return minutes*((1-w)*pr+w*cr)
    def shot(made, attempted, two=False):
        def pair(r):
            m,a=r.get(made),r.get(attempted)
            if not valid(m) or not valid(a) or m>a:return None
            if two:
                if not valid(r.get('FG3M'))or not valid(r.get('FG3A')):return None
                m-=r['FG3M'];a-=r['FG3A']
            return (m,a)if 0<=m<=a else None
        p=[(r,pair(r))for r in prior if pair(r)is not None]
        c=[(r,pair(r))for r in current if pair(r)is not None]
        if len(p)<8 or (current and len(c)!=len(current)):return None
        pm,pa=sum(v[0]for r,v in p),sum(v[1]for r,v in p)
        cm,ca=sum(v[0]for r,v in c),sum(v[1]for r,v in c)
        w=current_count/(current_count+8.)
        prior_rate=pa/sum(r['minutes']for r,v in p)
        current_rate=ca/sum(r['minutes']for r,v in c)if c else prior_rate
        attempts=minutes*((1-w)*prior_rate+w*current_rate)
        # Fifty prior-equivalent attempts stabilize small-sample shooting.
        prior_pct=(pm+1)/(pa+2)
        conversion=(cm+50*prior_pct)/(ca+50)
        return {'attempts':attempts,'conversion':conversion,'made':attempts*conversion}
    twos=shot('FGM','FGA',True);threes=shot('FG3M','FG3A');free=shot('FTM','FTA')
    points=2*twos['made']+3*threes['made']+free['made']if all(x is not None for x in (twos,threes,free))else None
    rebounds,assists=rate('REB'),rate('AST')
    values={'PTS':points,'REB':rebounds,'AST':assists,'FG3M':threes['made']if threes else None,
            'PRA':points+rebounds+assists if all(x is not None for x in (points,rebounds,assists))else None}
    return {'variant':variant,'minutes':minutes,'values':values,'shots':{'Two-point attempts':twos,'Three-point attempts':threes,'Free-throw attempts':free},
            'history_through':max(r['date']for r in prior+current),'current_games':len(current),
            'method':'Earlier-data-selected minutes/rate variant ('+variant+'); attempts/minute × shrunk shooting conversion. Rebounds/assists use minutes × observed rates. PRA sums same-game components; no multiplied marginal probabilities.'}


def attach(row, candidate, field, report):
    if not candidate or candidate['values'].get(field)is None:return
    row['Opportunity candidate']={'version':VERSION,'projection':candidate['values'][field],
                                  'variant':candidate.get('variant','median-minutes'),
                                  'minutes':candidate['minutes'],'shots':candidate['shots'],
                                  'history_through':candidate['history_through'],'method':candidate['method'],
                                  'benchmark':{k:v for k,v in report.items()if k!='residuals'}}
