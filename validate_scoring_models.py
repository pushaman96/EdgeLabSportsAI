"""Reproduce free-source development tests. Does not request sportsbook odds."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path

def run():
    from nfl_prop_model import load_season_stats,csv_url,SCHEDULE_URL
    from nfl_scoring_models import td_validate,total_validate
    players=[]
    for year in (2023,2024,2025):players.extend(load_season_stats('player',year))
    total=total_validate(csv_url(SCHEDULE_URL));total.pop('residuals',None)
    data={'generated_utc':datetime.now(timezone.utc).isoformat(),'NFL_anytime_touchdown':td_validate(players),'NFL_game_total':total,'status':'Historical development evidence only; no historical sportsbook returns and no live accuracy guarantee'}
    try:
        from nba_prop_model import current_roster_nba,reference_players,research
        from nba_season_prior import fetch_espn_logs
        # Fixed teams and alphabetical balanced roster sampling, not chosen by
        # outcome or forecast success. Current-roster selection is still a
        # limitation; this report does not claim whole-league validation.
        rosters={str(t):current_roster_nba(t)for t in (2,6,9,13,14,24)}
        refs=reference_players(rosters,12);logs=[];issues=[]
        with ThreadPoolExecutor(max_workers=6)as pool:
            tasks={(year,pid,name):pool.submit(fetch_espn_logs,year,pid,name)for year in (2024,2025,2026)for pid,name in refs}
            for (year,pid,name),task in tasks.items():
                try:logs.extend(task.result())
                except Exception:issues.append({'player':name,'season':year})
        # Fixed historical cutoff: a later run cannot train on 2026-27 results.
        fitted=research(logs,'2026-10-21')
        reports={cohort:r for (field,cohort),r in fitted['cohort_reports'].items()if field=='PRA'}
        data['NBA_PRA']={'reports':reports,'history_rows':len(logs),'reference_players':[name for pid,name in refs],'missing_sources':issues,'scope':'Current-roster-selected 12-player reference cohort across 6 fixed teams; limited development sample subject to selection bias, not whole-league or sportsbook validation. Production reviews validate their loaded history separately.'}
    except Exception:data['NBA_PRA']={'status':'History source unavailable; no validation pass invented'}
    target=Path('scoring_model_validation.json');temp=target.with_suffix('.tmp')
    temp.write_text(json.dumps(data,indent=2)+'\n');temp.replace(target)
    return data
if __name__=='__main__':run()
