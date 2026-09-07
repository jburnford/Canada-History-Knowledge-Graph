"""Reproduce the same-origin comparison and selected locality full-population counts."""
from pathlib import Path
import duckdb
import pandas as pd
ROOT=Path(__file__).resolve().parent
c=duckdb.connect(str(ROOT/'analysis.duckdb'),read_only=True)
d=c.execute('select serial,fo,mo,co,child_id,child_page,child_line from study_triads').fetchdf()
mp={'11201000':'French','21202001':'French','11101060':'English','11102050':'Scottish','11104040':'Irish','12106000':'German'}
for a in ['fo','mo','co']:d[a]=d[a].map(mp).fillna('Other/missing')
d=d[d.fo.eq(d.mo)&d.fo.ne('Other/missing')].copy()
d['page']=pd.to_numeric(d.child_page);d['line']=pd.to_numeric(d.child_line)
d=d.sort_values(['serial','page','line','child_id']);g=d.groupby('serial')
d['prev_origin']=g.co.shift();d['prev_page']=g.page.shift()
x=d[d.prev_origin.notna()].copy();x['change']=x.co.ne(x.prev_origin);x['pagebreak']=x.page.ne(x.prev_page)
x.groupby('pagebreak').agg(pairs=('child_id','size'),changes=('change','sum'),rate=('change','mean')).to_csv(ROOT/'results/same_origin_control.csv')
q="""select TCPUID_CSD_1881,dorigin_TCP,count(*) n from persons where remove_TCP='0'
and TCPUID_CSD_1881 in ('ON122012','ON122013','PE002012','NB030007') group by all order by 1,3 desc"""
y=c.execute(q).fetchdf();y['origin']=y.dorigin_TCP.map(mp).fillna('Other/missing')
y.to_csv(ROOT/'results/selected_locality_all_person_origins.csv',index=False)
c.close()
