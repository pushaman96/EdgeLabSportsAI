import copy
import unittest
from datetime import datetime,timedelta,timezone
from forecast_tracking import freeze
from online_learning import build_state,adjust_forecast,adjust_probability
from contextual_forecasts import nfl_availability,nfl_situation
from nba_prop_model import projection,normalize_logs,research,probability,reviews,minutes_replacement,nba_availability
from pick_history import grade_record
from dashboard_history import accuracy_summary


class TrackingTests(unittest.TestCase):
    now=datetime(2026,10,19,17,tzinfo=timezone.utc)
    def fixtures(self):
        start=(self.now+timedelta(hours=2)).isoformat()
        event=dict(id='odds',away_team='Away',home_team='Home',commence_time=start)
        board=dict(events=[dict(id='espn',name='Away at Home',date=start,season=dict(type=2))])
        row={'Game':'Away at Home','Player':'QB','Category':'Passing yards','Decision':'Pass','Selection':'Over','Line':200.5,'Odds':-110,'Sportsbook':'Book','Estimated win %':55,'Model':'fixture','Quote updated UTC':self.now.isoformat(),'Projection (yards)':210,'Base projection':200,'Candidate projection':220,'Base estimated win %':53,'Candidate win %':56}
        return row,event,board
    def test_pass_forecasts_freeze_separately_and_preserve_baselines(self):
        row,event,board=self.fixtures();before=copy.deepcopy(row)
        result=freeze([row],[event],board,now=self.now)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['strategy'],'Analysis')
        self.assertEqual(result[0]['event_id'],'espn')
        self.assertEqual(result[0]['base_projection'],200)
        self.assertEqual(result[0]['candidate_probability'],.56)
        self.assertEqual(row,before)
        self.assertEqual(accuracy_summary([dict(result[0],result='Win')],'NFL')['settled'],0)
    def test_late_stale_unmatched_and_unusable_forecasts_do_not_freeze(self):
        row,event,board=self.fixtures()
        for change in (dict(**{'Estimated win %':None}),dict(**{'Quote updated UTC':(self.now-timedelta(hours=1)).isoformat()}),dict(Game='Wrong game')):
            self.assertEqual(freeze([dict(row,**change)],[event],board,now=self.now),[])
        self.assertEqual(freeze([row],[event],board,now=self.now+timedelta(hours=3)),[])
        board['events'][0]['season']['type']=1
        self.assertEqual(freeze([row],[event],board,now=self.now),[])
    def test_distinct_lines_saved_but_each_player_game_learns_once(self):
        row,event,board=self.fixtures()
        records=freeze([row,dict(row,Line=210.5,Selection='Under')],[event],board,now=self.now)
        self.assertEqual(len(records),2)
        records=[dict(r,result='Win',actual=250,graded_utc=(self.now+timedelta(hours=6)).isoformat()) for r in records]
        state=build_state(records,self.now+timedelta(days=1))
        self.assertEqual(next(iter(state['groups'].values()))['games'],1)


class RollbackTests(unittest.TestCase):
    now=datetime(2026,10,19,tzinfo=timezone.utc)
    def rows(self,n,good=False):
        output=[]
        for i in range(n):
            start=self.now-timedelta(days=n-i+1)
            output.append(dict(id=str(i),event_id=str(i),player='QB',sport='NFL',model='fixture',category='Passing yards',strategy='Analysis',season_type='Regular season',evidence='Published before kickoff',published_utc=(start-timedelta(hours=1)).isoformat(),starts_utc=start.isoformat(),graded_utc=(start+timedelta(hours=4)).isoformat(),result='Loss',actual=200,projected_yards=250,base_projection=200,candidate_projection=200 if good else 250,base_probability=.8 if good else .5,candidate_probability=.5 if good else .8,online_version='frozen',probability=.5,direction='Over',line=200.5))
        return output
    def test_reduce_then_rollback_and_keep_original_forecast(self):
        five=next(iter(build_state(self.rows(5),self.now)['groups'].values()))
        self.assertEqual(five['application_weight'],.5)
        state=build_state(self.rows(10),self.now);group=next(iter(state['groups'].values()))
        self.assertEqual(group['application_weight'],0)
        row=dict(Model='fixture',Category='Passing yards')
        self.assertEqual(adjust_forecast(row,200,30,self.now,state),(200,30))
        self.assertEqual(adjust_probability(row,.7,self.now,state),.7)
        self.assertIn('Candidate win %',row)
    def test_one_bad_game_not_rollback_and_good_shadow_games_can_recover(self):
        self.assertEqual(next(iter(build_state(self.rows(1),self.now)['groups'].values()))['application_weight'],1)
        old=[dict(r,**{field:(datetime.fromisoformat(r[field])-timedelta(days=40)).isoformat() for field in ('published_utc','starts_utc','graded_utc')}) for r in self.rows(10)]
        records=old+[dict(r,event_id='new'+r['id']) for r in self.rows(20,good=True)]
        group=next(iter(build_state(records,self.now)['groups'].values()))
        self.assertEqual(group['application_weight'],1)
    def test_future_outcome_cannot_trigger_rollback(self):
        rows=self.rows(10)
        asof=datetime.fromisoformat(rows[4]['graded_utc'])-timedelta(seconds=1)
        self.assertEqual(next(iter(build_state(rows,asof)['groups'].values()))['application_weight'],1)


class ContextTests(unittest.TestCase):
    def roster_history(self):
        roster=[dict(name='Active RB',status='Active'),dict(name='Absent RB',status='Active'),dict(name='Primary QB',status='Active'),dict(name='Backup QB',status='Active')]
        rows=[]
        for week in range(1,5):
            for name,pos,carries,attempts,yards in [('Active RB','RB',10,0,0),('Absent RB','RB',10,0,0),('Primary QB','QB',0,30,240),('Backup QB','QB',0,10,50)]:
                rows.append(dict(player_display_name=name,position=pos,season=2026,week=week,team='A',carries=carries,targets=carries,attempts=attempts,passing_yards=yards))
        return roster,rows
    def test_only_confirmed_absences_redistribute_and_caps_apply(self):
        roster,rows=self.roster_history()
        injuries=dict(statuses={('Team','absentrb'):'Questionable'})
        args=('Active RB','Rushing yards','A','Team',2026,5,rows,roster)
        self.assertEqual(nfl_availability(*args,injuries)['workload_factor'],1)
        injuries['statuses'][('Team','absentrb')]='Out'
        self.assertAlmostEqual(nfl_availability(*args,injuries)['workload_factor'],1.15)
        self.assertEqual(nfl_availability(*args[:-2],rows[:1],roster,injuries)['workload_factor'],1)
    def test_replacement_qb_efficiency_requires_actual_history(self):
        roster,rows=self.roster_history();inj=dict(statuses={('Team','primaryqb'):'Out'})
        result=nfl_availability('Backup QB','Passing yards','A','Team',2026,5,rows,roster,inj)
        self.assertEqual(result['efficiency_factor'],.85)
        for row in rows:
            if row['player_display_name']=='Backup QB':row['attempts']=1
        self.assertEqual(nfl_availability('Backup QB','Passing yards','A','Team',2026,5,rows,roster,inj)['efficiency_factor'],1)
    def test_situation_excludes_future_scores_and_probabilities_sum_to_one(self):
        games=[];rows=[]
        for n in range(10):
            games.append(dict(game_id=str(n),gameday=f'2026-09-{n+1:02}',game_type='REG',home_team='A',away_team='B',home_score=30 if n%2 else 10,away_score=20))
            for team in ['A','B']:rows.append(dict(game_id=str(n),team=team,attempts=20 if n%2 else 40,carries=30 if n%2 else 15))
        result=nfl_situation('A','B','2026-09-09',games,rows)
        altered=[dict(g,home_score=99999) if g['gameday']>='2026-09-09' else g for g in games]
        self.assertEqual(result,nfl_situation('A','B','2026-09-09',altered,rows))
        self.assertAlmostEqual(sum(result['probabilities'].values()),1)
        self.assertTrue(.9<=result['passing_factor']<=1.1)
        self.assertIsNone(nfl_situation('A','B','2026-09-02',games,rows))


class NbaModelTests(unittest.TestCase):
    def logs(self,n=50):
        rows=[];start=datetime(2026,1,1)
        for i in range(n):
            rows.append(dict(player='p',name='Player One',team='100',date=(start+timedelta(days=i)).date().isoformat(),game=str(i),minutes=20+i%5,PTS=10+i%4,REB=5,AST=4,FG3M=2))
        return rows
    def test_minutes_times_rate_uses_prior_history_and_minutes_caps(self):
        rows=self.logs();f=projection(rows,'PTS')
        self.assertAlmostEqual(f[0],f[1]*sum(r['PTS'] for r in rows[-12:])/sum(r['minutes'] for r in rows[-12:]))
        self.assertLessEqual(projection([dict(r,minutes=60) for r in rows],'PTS')[1],40)
        self.assertIsNone(projection(rows[:7],'PTS'))
    def test_future_logs_do_not_change_research_and_split_dates_are_disjoint(self):
        rows=self.logs();cutoff=rows[30]['date']
        a=research(rows,cutoff)
        b=research([dict(r,PTS=9999) if r['date']>=cutoff else r for r in rows],cutoff)
        self.assertEqual(a,b)
        self.assertEqual(len(a['history']['p','100']),30)
    def test_new_team_has_no_inherited_role_and_insufficient_errors_no_probability(self):
        data=research(self.logs(),'2026-04-01')
        self.assertFalse(data['history'].get(('p','newteam')))
        self.assertIsNone(probability(20,20.5,[1,2]))
        self.assertTrue(.05<=probability(20,20.5,[0]*50)<=.95)
    def test_nba_normalization_rejects_wrong_season_and_duplicates(self):
        row=dict(SEASON_ID='22025',WL='W',MIN=30,PTS=20,REB=5,AST=4,FG3M=2,PLAYER_ID=1,PLAYER_NAME='Player',TEAM_ID=100,GAME_ID='g',GAME_DATE='2026-01-01')
        self.assertEqual(normalize_logs([row],2026)[0]['minutes'],30)
        with self.assertRaises(ValueError):normalize_logs([row],2027)
        with self.assertRaises(ValueError):normalize_logs([row,row],2026)
    def test_minutes_replacement_conservatively_caps_increment(self):
        rows=self.logs(10)+[dict(r,name='Absent Player',player='other',minutes=35) for r in self.logs(10)]
        minutes,factor=minutes_replacement(rows,{'playerone','absentplayer'},{'absentplayer'},30)
        self.assertAlmostEqual(factor,1.1);self.assertAlmostEqual(minutes,33)
    def test_stale_injury_coverage_is_unverified(self):
        now=datetime(2026,10,20,tzinfo=timezone.utc)
        injuries=dict(source_timestamp='2026-10-19T23:00:00Z',retrieved='2026-10-20 00:00 UTC',teams=['Team'],rows=[])
        self.assertEqual(nba_availability(injuries,'Team','Player',now),'Not listed')
        injuries['source_timestamp']='2026-10-18T00:00:00Z'
        self.assertIsNone(nba_availability(injuries,'Team','Player',now))
    def test_nba_final_minutes_are_saved_as_opportunities(self):
        record=dict(event_id='g',sport='NBA',category='Points',player='Player',result='Pending',line=20.5,direction='Over',odds=-110,projected_count=22,expected_opportunities=30)
        data=dict(header=dict(id='g',competitions=[dict(status=dict(type=dict(completed=True)))]),boxscore=dict(players=[dict(statistics=[dict(labels=['MIN','PTS'],athletes=[dict(athlete=dict(displayName='Player'),stats=['32:30','24'])])])]))
        graded=grade_record(record,data)
        self.assertEqual(graded['result'],'Win');self.assertEqual(graded['actual_opportunities'],32.5)
    def test_nba_end_to_end_forecast_uses_roster_mapping_and_freezes_pick(self):
        now=datetime(2026,10,19,12,tzinfo=timezone.utc)
        logs=[]
        for i in range(120):
            minutes=20+i*.1
            logs.append(dict(player='nba-player',name='Player One',team='100',date=(now-timedelta(days=120-i)).date().isoformat(),game=str(i),minutes=minutes,PTS=minutes,REB=minutes*.3,AST=minutes*.2,FG3M=minutes*.05))
        start=(now+timedelta(days=1)).isoformat()
        event=dict(id='odds',away_team='Away',home_team='Home',commence_time=start,bookmakers=[dict(title='Book',markets=[dict(key='player_points',last_update=now.isoformat(),outcomes=[dict(description='Player One',name='Over',point=5.5,price=-110)])])])
        source=dict(id='espn',name='Away at Home',date=start,season=dict(type=2,year=2027),competitions=[dict(competitors=[dict(team=dict(displayName='Home',id='espn-team',abbreviation='GS')),dict(team=dict(displayName='Away',id='away-team',abbreviation='LAL'))])])
        board=dict(events=[source])
        data=dict(season=2027,logs=logs,team_ids=dict(GSW='100'),retrieved=now.isoformat())
        injuries=dict(source_timestamp=now.isoformat(),retrieved=now.strftime('%Y-%m-%d %H:%M UTC'),teams=['Home','Away'],rows=[])
        roster={'Home':[dict(name='Player One',status='Active')],'Away':[]}
        output=reviews([event],board,data,injuries,roster,now)
        self.assertEqual(len(output),1)
        row=output[0]
        self.assertIsNotNone(row['Estimated win %'])
        self.assertIn(row['Decision'],('Watch — experimental','Pass'))
        self.assertIn('Validation',row)
        self.assertEqual(row['Decision']=='Watch — experimental',row['Validation']['passed'] and row['Model edge (pp)']>=5)
        self.assertGreater(row['Projection (count)'],0)
        self.assertIn('Minutes forecast',row)
        saved=freeze(output,[event],board,sport='NBA',now=now)
        self.assertEqual(len(saved),1)
        self.assertEqual(saved[0]['sport'],'NBA')
        self.assertEqual(saved[0]['forecast_context']['Opportunity type'],'Minutes')
        roster['Home'][0]['status']='Inactive'
        blocked=reviews([event],board,data,injuries,roster,now)[0]
        self.assertEqual(blocked['Decision'],'Pass')
        self.assertIsNone(blocked['Estimated win %'])

    def test_preseason_never_produces_prop_recommendations(self):
        now=datetime(2026,10,19,tzinfo=timezone.utc);start=(now+timedelta(days=1)).isoformat()
        event=dict(away_team='Away',home_team='Home',commence_time=start)
        board=dict(events=[dict(name='Away at Home',date=start,season=dict(type=1))])
        self.assertEqual(reviews([event],board,{},None,{},now),[])


if __name__=='__main__':unittest.main()

