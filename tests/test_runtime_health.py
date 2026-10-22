import json,tempfile,types,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import requests
import runtime_health as h

class RuntimeHealthTests(unittest.TestCase):
    def setUp(self):
        h._FEEDS.clear();h._FILES.clear();h._EVENTS.clear();h._MODULES.clear()
        self.clock=100.;self.timer=patch.object(h.time,'monotonic',side_effect=lambda:self.clock);self.timer.start();self.addCleanup(self.timer.stop)
        self.client=Mock();self.client.get.return_value.json.return_value={'events':[]}
    def get(self,**kw):return h.public_json('scoreboard','https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard',client=self.client,validate=lambda d:isinstance(d.get('events'),list),**kw)
    def test_warm_cache_avoids_network_and_cannot_be_mutated_by_caller(self):
        data,meta=self.get();data['events'].append('bad')
        self.assertEqual(self.get()[0]['events'],[]);self.client.get.assert_called_once()
        self.assertEqual(self.client.get.call_args.kwargs['timeout'],(2,5))
    def test_transient_failure_retains_original_timestamp_then_recovers(self):
        _,meta=self.get();self.clock+=31
        self.client.get.side_effect=requests.Timeout('secret URL must not be logged')
        data,stale=self.get();self.assertTrue(stale['stale']);self.assertEqual(stale['retrieved_utc'],meta['retrieved_utc'])
        self.get();self.assertEqual(self.client.get.call_count,2)
        self.clock+=31;self.client.get.side_effect=None
        self.assertFalse(self.get()[1]['stale']);self.assertEqual(self.client.get.call_count,3)
        self.assertNotIn('secret',json.dumps(list(h._EVENTS.values())))
    def test_no_data_or_overage_is_unknown_not_zero(self):
        self.client.get.side_effect=requests.Timeout()
        for _ in range(2):
            with self.assertRaises(h.FeedUnavailable):self.get()
        self.assertEqual(self.client.get.call_count,1)
        self.clock+=31;self.client.get.side_effect=None;self.get()
        self.clock+=121;self.client.get.side_effect=requests.Timeout()
        with self.assertRaises(h.FeedUnavailable):self.get()
    def test_wrong_game_never_cached_or_used(self):
        self.client.get.return_value.json.return_value={'header':{'id':'wrong'}}
        with self.assertRaises(h.FeedUnavailable):h.public_json('game','https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary',validate=lambda d:d.get('header',{}).get('id')=='1',client=self.client)
    def test_paid_or_private_requests_never_enter_recovery(self):
        for url in ('https://api.the-odds-api.com/v4/sports','https://api.github.com/repos/x','https://site.api.espn.com/path?apiKey=private','https://raw.githubusercontent.com/other/repo/main/file'):
            with self.assertRaises(ValueError):h.public_json('bad',url,client=self.client)
        self.client.get.assert_not_called()
    def test_manual_refresh_preserves_cooldown_and_last_good(self):
        self.get();h.invalidate_public('scoreboard');self.client.get.side_effect=requests.Timeout();self.get()
        h.invalidate_public();self.get();self.assertEqual(self.client.get.call_count,2)
    def test_final_summary_cached_ten_minutes_and_identity_checked(self):
        data={'header':{'id':'123','competitions':[{'status':{'type':{'completed':True}}}]}}
        with patch.object(h.requests,'get',return_value=types.SimpleNamespace(raise_for_status=lambda:None,json=lambda:data))as get:
            h.summary('football/nfl','123');self.clock+=590;h.summary('football/nfl','123');self.assertEqual(get.call_count,1)
            self.clock+=11;h.summary('football/nfl','123');self.assertEqual(get.call_count,2)
    def test_snapshot_compacts_reads_once_and_refreshes_on_version_change(self):
        with tempfile.TemporaryDirectory()as directory:
            p=Path(directory)/'report.json';p.write_text(json.dumps({'value':1,'large':'x'*10000}))
            select=Mock(side_effect=lambda d:{'value':d['value']})
            self.assertEqual(h.snapshot(p,'small',select,{}),{'value':1})
            self.assertEqual(h.snapshot(p,'small',select,{}),{'value':1});self.assertEqual(select.call_count,1)
            p.write_text(json.dumps({'value':22}));self.assertEqual(h.snapshot(p,'small',select,{})['value'],22)
            self.assertNotIn('large',str(h._FILES))
            p.write_text('{broken');self.assertEqual(h.snapshot(p,'small',select,{})['value'],22)
            self.clock+=601;self.assertEqual(h.snapshot(p,'small',select,{}),{})
    def test_modules_reload_only_when_source_changed(self):
        with tempfile.TemporaryDirectory()as directory:
            p=Path(directory)/'module.py';p.write_text('v=1')
            module=types.SimpleNamespace(__file__=str(p),__name__='fixture')
            with patch.object(h.importlib,'reload',return_value=module)as reload:
                h.reload_if_changed(module);h.reload_if_changed(module);reload.assert_not_called()
                p.write_text('v=222');h.reload_if_changed(module);h.reload_if_changed(module);reload.assert_called_once()
    def test_unexpected_error_releases_inflight_without_hiding_bug(self):
        self.client.get.side_effect=RuntimeError('programming bug')
        with self.assertRaises(RuntimeError):self.get()
        self.assertFalse(next(iter(h._FEEDS.values()))['inflight'])
    def test_live_and_final_games_do_not_share_cache(self):
        data={'header':{'id':'123','competitions':[{'status':{'type':{'completed':False}}}]}}
        with patch.object(h.requests,'get',return_value=types.SimpleNamespace(raise_for_status=lambda:None,json=lambda:data))as get:
            h.summary('football/nfl','123');self.clock+=21;h.summary('football/nfl','123');self.assertEqual(get.call_count,2)

class DashboardWorkTests(unittest.TestCase):
    def test_collapsed_detailed_archive_never_reads_large_file(self):
        import sys
        from contextlib import nullcontext
        from paired_forecasts import render
        ui=types.SimpleNamespace(expander=lambda *a,**k:nullcontext(),toggle=lambda *a,**k:False,caption=lambda *a,**k:None)
        with patch.dict(sys.modules,{'streamlit':ui}),patch('runtime_health.snapshot',side_effect=AssertionError('Large file should not be read')):
            render([],'NBA')
    def test_installed_identical_archive_needs_no_network_write(self):
        import sys
        from automatic_reports import autosave_report
        ui=types.SimpleNamespace(session_state={})
        with patch.dict(sys.modules,{'streamlit':ui}),patch('automatic_reports.load_report',return_value='same report'),patch('automatic_reports.flush_reports',side_effect=AssertionError('No network needed')):
            autosave_report('Report','same report','fixture.csv')
        self.assertNotIn('fixture.csv',ui.session_state.get('pending_report_saves',{}))
        self.assertTrue(ui.session_state['automatic_report_digests'].get('fixture.csv'))
