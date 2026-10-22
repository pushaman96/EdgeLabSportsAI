import copy,json,unittest
from market_reasoning import analysis,apply,outcome,UNITS
from saved_pick_explanation import saved_market_reasoning
class MarketReasoningTests(unittest.TestCase):
    def test_same_receiving_performance_wins_receptions_loses_yards_td(self):
        rows=[dict(Game='A at B',Player='TE',Category=c,Selection='Over',Line=l,Decision='Watch',**{'Estimated win %':61,'Odds':-110})for c,l in [('Receptions',5.5),('Receiving yards',49.5),('Anytime touchdown',.5)]]
        before=copy.deepcopy(rows);result=apply(rows,'NFL')
        cases=result[0]['Market reasoning']['cross_market_example']
        self.assertEqual([r['Result']for r in cases['markets']],['Win','Loss','Loss'])
        self.assertIn('not this player',cases['label'])
        self.assertEqual(rows,before)
        for row,new in zip(rows,result):
            self.assertEqual({k:new[k]for k in row},row)
        json.dumps(result,allow_nan=False)
    def test_nba_components_sum_to_pra_but_have_distinct_results(self):
        rows=[dict(Game='A at B',Player='P',Category=c,Selection='Over',Line=l)for c,l in [('Points',19.5),('PRA',30.5),('Three-pointers made',2.5)]]
        cross=apply(rows,'NBA')[0]['Market reasoning']['cross_market_example']
        self.assertEqual([r['Result']for r in cross['markets']],['Win','Loss','Loss'])
        self.assertEqual(cross['stat_line']['PRA'],sum(cross['stat_line'][k]for k in ('Points','Rebounds','Assists')))
        self.assertIn('not be multiplied',cross['correlation_note'])
    def test_integer_push_fractional_lines_and_under(self):
        for category in UNITS:
            self.assertEqual(outcome(category,'Over',5,5),'Push')
            self.assertEqual(outcome(category,'Over',5.5,6),'Win')
            self.assertEqual(outcome(category,'Under',5.5,5),'Win')
            self.assertEqual(outcome(category,'Under',5.5,6),'Loss')
        self.assertIn('6+',analysis(dict(Category='Receptions',Selection='Over',Line=5.5))['win_condition'])
        self.assertIn('4 or fewer',analysis(dict(Category='Receptions',Selection='Under',Line=5))['win_condition'])
    def test_negative_yards_are_possible_but_negative_counts_are_invalid(self):
        self.assertEqual(outcome('Rushing yards','Under',.5,-2),'Win')
        self.assertEqual(outcome('Receptions','Under',.5,-2),'Unknown')
        self.assertIn('-2 or fewer',analysis(dict(Category='Rushing yards',Selection='Under',Line=-1.5))['win_condition'])
    def test_no_missing_stats_zero_fabrication_or_unsupported_market(self):
        for missing in (None,False,float('nan'),float('inf'),'unknown'):
            self.assertEqual(outcome('Receiving yards','Over',49.5,missing),'Unknown')
        self.assertEqual(outcome('Unknown market','Over',1,2),'Unknown')
        self.assertFalse(analysis(dict(Category='Receptions',Selection='Over',Line=None))['supported'])
        self.assertEqual(outcome('Anytime touchdown','Over',.5,None),'Unknown')
        self.assertEqual(outcome('Anytime touchdown','Over',.5,0),'Loss')
        self.assertEqual(outcome('Anytime touchdown','Under',.5,0),'Win')
        self.assertEqual(outcome('Anytime touchdown','Over',1.5,2),'Unknown')
    def test_price_matters_and_does_not_reuse_probability_for_examples(self):
        row=dict(Category='Receiving yards',Selection='Over',Line=49.5,Odds=-110,**{'Estimated win %':60,'Projection (yards)':55})
        a=analysis(row)
        self.assertIn('52.4%',a['price_comparison']);self.assertIn('+7.6',a['price_comparison'])
        b=analysis(dict(row,Odds=-200))
        self.assertIn('-6.7',b['price_comparison'])
        self.assertTrue(all('Probability'not in r for r in a['illustrative_outcomes']))
        self.assertIn('requires model reanalysis',a['price_comparison'])
    def test_same_player_different_games_never_combined_and_missing_market_not_invented(self):
        rows=[dict(Game=g,Player='P',Category=c,Selection='Over',Line=5.5)for g,c in [('A','Receptions'),('B','Receiving yards')]]
        self.assertTrue(all('cross_market_example'not in r['Market reasoning']for r in apply(rows,'NFL')))
    def test_moneyline_and_saved_legacy_explanation_do_not_rewrite_records(self):
        record=dict(category='Moneyline',direction='Win',line=None,odds=150,probability=.55)
        before=copy.deepcopy(record);a=saved_market_reasoning(record)
        self.assertEqual(record,before);self.assertIn('40.0%',a['price_comparison'])
        self.assertEqual([r['Result']for r in a['illustrative_outcomes']],['Win','Loss','Push'])
    def test_frozen_record_retains_reasoning(self):
        from pick_history import make_record
        from datetime import datetime,timezone,timedelta
        now=datetime.now(timezone.utc)
        row=apply([dict(Game='A at B',Player='P',Category='Receptions',Selection='Over',Line=5.5,Odds=-110,Sportsbook='Fixture',Decision='Watch',**{'Estimated win %':60,'Quote updated UTC':now.isoformat()})],'NFL')[0]
        record=make_record(row,'e',(now+timedelta(hours=1)).isoformat(),now=now)
        self.assertEqual(record['forecast_context']['Market reasoning'],row['Market reasoning'])

    def test_diagnostic_checks_exact_market_before_issuing_pick(self):
        from game_day_diagnostics import evidence,pacific_day
        from datetime import datetime,timezone
        now=datetime.now(timezone.utc)
        report=dict(passed=True,tests_run=298,checked_utc=now.isoformat(),pacific_date=pacific_day(now),source_hash='test')
        row=dict(Category='Receptions',Selection='Over',Line=None,Decision='Watch',Validation={'passed':True},**{'Estimated win %':65,'Quote updated UTC':now.isoformat()})
        audit=evidence(row,report,now,'test')
        self.assertFalse(audit['ready']);self.assertTrue(any('Exact market' in x for x in audit['issues']))
        self.assertTrue(evidence(dict(row,Line=5.5),report,now,'test')['ready'])
    def test_invalid_touchdown_threshold_and_unknown_stat_not_settled(self):
        self.assertEqual(outcome('Anytime touchdown','Over','bad',1),'Unknown')
        self.assertFalse(analysis(dict(Category='Anytime touchdown',Selection='Over',Line='bad'))['supported'])
    def test_shared_diagnostic_attaches_reasoning_without_promoting_passes(self):
        from unittest.mock import patch
        from game_day_diagnostics import apply as diagnose,pacific_day
        from datetime import datetime,timezone
        now=datetime.now(timezone.utc)
        report=dict(passed=True,tests_run=298,checked_utc=now.isoformat(),pacific_date=pacific_day(now),source_hash='test')
        row=dict(Game='A at B',Player='P',Category='Points',Selection='Under',Line=25.5,Decision='Pass',Validation={'passed':True},**{'Estimated win %':65,'Quote updated UTC':now.isoformat()})
        with patch('game_day_diagnostics.load',return_value=report),patch('game_day_diagnostics.fingerprint',return_value='test'):
            result=diagnose([row],'NBA',now)[0]
        self.assertEqual(result['Decision'],'Pass');self.assertIn('Market reasoning',result)
        self.assertIn('25 or fewer',result['Market reasoning']['win_condition'])
