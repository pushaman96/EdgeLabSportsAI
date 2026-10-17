import sys,types,unittest
from unittest.mock import patch
from pick_cards import render_pick_cards
class Box:
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def container(self,**k):return self
    def image(self,*a,**k):pass
    def write(self,*a,**k):pass
    def metric(self,*a,**k):pass
class CardTests(unittest.TestCase):
    def test_cards_paginate_and_keep_originals(self):
        st=types.ModuleType('streamlit');st.session_state={};writes=[]
        st.columns=lambda n:[Box() for _ in range(n if isinstance(n,int) else len(n))]
        st.selectbox=lambda label,options,**k:options[0]
        st.write=lambda value:writes.append(value);st.caption=lambda *a:None;st.info=lambda *a:None;st.expander=lambda *a,**k:Box()
        records=[dict(id=str(i),player='Player '+str(i),category='Passing yards',direction='Under',line=200.5,probability=.6,odds=-110,strategy='Original') for i in range(28)]
        with patch.dict(sys.modules,{'streamlit':st}):render_pick_cards(records,'NFL')
        titles=[w for w in writes if w.startswith('**Player')]
        self.assertEqual(len(titles),6)
        self.assertNotIn('source_audit',records[0])
