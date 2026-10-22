"""Cold-load routing tests; no network, model fitting or odds requests."""
import ast
from pathlib import Path
import types
import sys
import unittest
from unittest.mock import MagicMock,patch

class PropLoadRoutingTests(unittest.TestCase):
    def run_phase(self,mode):
        node=next(n for n in ast.parse(Path('nfl_prop_model.py').read_text()).body if isinstance(n,ast.FunctionDef)and n.name=='render_prop_research')
        trigger=next(n for n in node.body if isinstance(n,ast.If)and ast.unparse(n.test)=='auto_analyze or analyze')
        node.body=node.body[:node.body.index(trigger)+1]
        work=next(n for n in trigger.body[0].body if isinstance(n,ast.With))
        stop=next(i for i,n in enumerate(work.body)if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='stage' for t in n.targets))
        work.body=work.body[:stop]
        st=MagicMock();st.selectbox.return_value=mode;st.button.return_value=False
        calls=[]
        def load(*a,**k):calls.append('base');return {}
        module=types.ModuleType('nfl_workload_lab')
        module.load_experimental_research=lambda *a,**k:calls.append('experimental')or {}
        ns={'st':st,'event_context':lambda *a:{'regular':True,'season':2026},'load_prop_research':load}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'route','exec'),ns)
        event={'id':'one','away_team':'Away','home_team':'Home','commence_time':'2026-10-25T17:00:00Z'}
        with patch.dict(sys.modules,{'nfl_workload_lab':module}):
            ns['render_prop_research'](event,{},[],'now',True)
        return calls
    def test_experimental_does_not_load_base_twice(self):
        self.assertEqual(self.run_phase('Experimental opportunity model — paper testing'),['experimental'])
    def test_original_still_loads_its_model(self):
        self.assertEqual(self.run_phase('Original model'),['base'])
