"""Reproduce the 1881 household-origin study from the unmodified TCP CSV.

Run: python3 research/1881_family_origins_20260907/analyze.py
Requires duckdb, pandas, numpy, matplotlib. The DB is a disposable local cache.
Relationships are inferred household configurations, never genealogical links.
"""
from pathlib import Path
import hashlib
import json
import duckdb
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/home/jic823/borealis_1881/1881_v20251217.csv')
LABELS = SOURCE.with_name('1881_value_labels.json')
OUT = ROOT / 'results'
OUT.mkdir(exist_ok=True)
c = duckdb.connect(str(ROOT / 'analysis.duckdb'))
c.execute('set threads=4')
c.execute('create table if not exists persons as select *,try_cast(age as double) age_years,try_cast(line as int) line_num from read_csv(?,all_varchar=true)', [str(SOURCE)])
c.execute("""create or replace temp view ordered as
 select *,row_number() over(partition by serial order by try_cast(pageno as int),line_num,unique_identifier) pos
 from persons where remove_TCP='0'""")
c.execute("""create or replace table family_candidates as
 select serial,count(*) n,
 count(*) filter(where sex='Male' and marst_TCP='2' and age_years>=20) nm,
 count(*) filter(where sex='Female' and marst_TCP='2' and age_years>=20) nf,
 count(*) filter(where marst_TCP='1' and age_years between 0 and 14) nc,
 count(distinct province) np,count(distinct TCPUID_CSD_1881) ncsd
 from ordered group by serial
 having nm=1 and nf=1 and nc>=1 and n=nc+2 and np=1 and ncsd=1""")
c.execute("""create or replace table candidate_triads as
 select h.serial,h.n,h.nc,ch.unique_identifier child_id,f.unique_identifier father_id,m.unique_identifier mother_id,
 ch.province,ch.distnam,ch.sdistnam,ch.TCPUID_CSD_1881 csd,
 concat_ws('|',ch.province,ch.distno,ch.sdistlet,coalesce(ch.divno,''),coalesce(ch.divno_2,''),coalesce(ch.sdistlet_2,'')) enumeration_unit,
 ch.sex,ch.age_years child_age,f.age_years father_age,m.age_years mother_age,
 ch.namlast child_surname,f.namlast father_surname,m.namlast mother_surname,
 ch.namfrst child_name,f.namfrst father_name,m.namfrst mother_name,
 ch.dorigin_TCP co,f.dorigin_TCP fo,m.dorigin_TCP mo,
 ch.dorigin cr,f.dorigin fr,m.dorigin mr,
 ch.dbirthpl_TCP cb,f.dbirthpl_TCP fb,m.dbirthpl_TCP mb,
 ch.drelign_TCP crel,f.drelign_TCP frel,m.drelign_TCP mrel,
 ch.dorigin_evaluation_flag_TCP cf,f.dorigin_evaluation_flag_TCP ff,m.dorigin_evaluation_flag_TCP mf,
 ch.dorigin_2_TCP co2,f.dorigin_2_TCP fo2,m.dorigin_2_TCP mo2,
 ch.url child_url,f.url father_url,m.url mother_url,
 ch.pageno child_page,f.pageno father_page,m.pageno mother_page,
 ch.line child_line,f.line father_line,m.line mother_line,
 ch.reel_nac,ch.hhnbr,f.pos father_pos,m.pos mother_pos,ch.pos child_pos,
 coalesce(lower(trim(ch.namlast))=lower(trim(f.namlast)) and length(trim(ch.namlast))>0
 and f.age_years-ch.age_years between 15 and 65
 and m.age_years-ch.age_years between 15 and 50,false) valid_child
 from family_candidates h
 join ordered f on h.serial=f.serial and f.sex='Male' and f.marst_TCP='2' and f.age_years>=20
 join ordered m on h.serial=m.serial and m.sex='Female' and m.marst_TCP='2' and m.age_years>=20
 join ordered ch on h.serial=ch.serial and ch.marst_TCP='1' and ch.age_years between 0 and 14""")
c.execute("""create or replace table study_triads as
 select * from candidate_triads where serial in
 (select serial from candidate_triads group by serial having bool_and(valid_child)
 and min(father_pos)=1 and min(mother_pos)=2 and min(child_pos)=3)""")
d = c.execute('select * from study_triads').fetchdf()
codes = {'11201000':'French','21202001':'French','11101060':'English',
         '11102050':'Scottish','11104040':'Irish','12106000':'German'}
for prefix in 'cfm':
    d[prefix+'origin'] = d[prefix+'o'].map(codes).fillna('Other/missing')
d['maternal'] = d.corigin.eq(d.morigin)
d['paternal'] = d.corigin.eq(d.forigin)
d['same_page'] = d.child_page.eq(d.father_page) & d.child_page.eq(d.mother_page)
d['clean_codes'] = d[['cf','ff','mf','co2','fo2','mo2']].isna().all(axis=1)
mixed = d[d.forigin.ne(d.morigin) & d.forigin.ne('Other/missing') & d.morigin.ne('Other/missing')].copy()
mixed.to_csv(OUT/'mixed_triads.csv.gz',index=False)
hh = mixed.groupby('serial').agg(province=('province','first'),distnam=('distnam','first'),
 sdistnam=('sdistnam','first'),csd=('csd','first'),enumeration_unit=('enumeration_unit','first'),
 forigin=('forigin','first'),morigin=('morigin','first'),frel=('frel','first'),mrel=('mrel','first'),
 n=('child_id','size'),maternal=('maternal','mean'),paternal=('paternal','mean'),
 all_maternal=('maternal','all'),all_paternal=('paternal','all'),
 same_page=('same_page','all'),clean_codes=('clean_codes','all'),max_age=('child_age','max'))
hh.to_csv(OUT/'mixed_households.csv')

def tab(frame, groups):
    return frame.groupby(groups,dropna=False).agg(children=('child_id','size'),households=('serial','nunique'),
      maternal=('maternal','mean'),paternal=('paternal','mean')).reset_index()

tab(mixed,['province']).to_csv(OUT/'province.csv',index=False)
tab(mixed,['forigin','morigin']).to_csv(OUT/'origin_pairs.csv',index=False)
tab(mixed,['province','forigin','morigin']).to_csv(OUT/'province_pairs.csv',index=False)
local = hh.groupby(['province','distnam','sdistnam','csd']).agg(households=('n','size'),children=('n','sum'),
 maternal=('maternal','mean'),paternal=('paternal','mean'),all_maternal=('all_maternal','sum'),
 all_paternal=('all_paternal','sum')).reset_index()
local.to_csv(OUT/'localities.csv',index=False)
units = hh.groupby(['province','enumeration_unit']).agg(households=('n','size'),children=('n','sum'),
 maternal=('maternal','mean'),paternal=('paternal','mean'),all_maternal=('all_maternal','sum'),
 all_paternal=('all_paternal','sum')).reset_index()
units.to_csv(OUT/'enumeration_units.csv',index=False)

# An equally weighted household is the main unit, preventing large sibships from dominating.
checks=[]
for name, filt in [('all',np.ones(len(hh),dtype=bool)),('same manuscript page',hh.same_page),
 ('no origin flags/secondary codes',hh.clean_codes),('all children under 10',hh.max_age.lt(10)),
 ('two or more children',hh.n.ge(2)),('same recorded religion',hh.frel.eq(hh.mrel)&hh.frel.notna())]:
 x=hh[filt]
 checks.append(dict(specification=name,households=len(x),children=int(x.n.sum()),
   maternal=x.maternal.mean(),paternal=x.paternal.mean(),
   all_maternal=int(x.all_maternal.sum()),all_paternal=int(x.all_paternal.sum())))
pd.DataFrame(checks).to_csv(OUT/'sensitivity.csv',index=False)

# Leave-one-household-out local consistency: neighbours predict the held-out household.
# This is descriptive validation of clustering, not a causal enumerator estimate.
hh['pair'] = hh.forigin+' / '+hh.morigin
for key in ['enumeration_unit','csd']:
    sums=hh.groupby(key).maternal.transform('sum'); sizes=hh.groupby(key).maternal.transform('size')
    hh[key+'_loo']=(sums-hh.maternal)/(sizes-1)
    hh[key+'_n']=sizes
prediction=[]
for key in ['enumeration_unit','csd']:
 for low,high,name in [(0,.1,'paternal neighbours'),(.9,1.000001,'maternal neighbours')]:
  x=hh[(hh[key+'_n']>=10)&hh[key+'_loo'].ge(low)&hh[key+'_loo'].lt(high)]
  prediction.append(dict(geography=key,neighbours=name,households=len(x),maternal=x.maternal.mean(),paternal=x.paternal.mean()))
pd.DataFrame(prediction).to_csv(OUT/'leave_one_out.csv',index=False)

# Reallocation is a defined counterfactual, not a correction to "true ethnicity".
effect=[]
for province,x in mixed.groupby('province'):
 for origin in codes.values():
  if any(z['province']==province and z['origin']==origin for z in effect): continue
  observed=int(x.corigin.eq(origin).sum()); paternal=int(x.forigin.eq(origin).sum()); maternal=int(x.morigin.eq(origin).sum())
  effect.append(dict(province=province,origin=origin,observed=observed,all_paternal=paternal,all_maternal=maternal,observed_minus_paternal=observed-paternal))
pd.DataFrame(effect).to_csv(OUT/'classification_counterfactual.csv',index=False)

fb=mixed[(mixed.forigin.eq('French') & mixed.morigin.isin(['English','Scottish','Irish'])) |
         (mixed.morigin.eq('French') & mixed.forigin.isin(['English','Scottish','Irish']))].copy()
fb['direction']=np.where(fb.forigin.eq('French'),'French man','French woman')
fb['french']=fb.corigin.eq('French')
fb.groupby(['province','direction']).agg(children=('child_id','size'),households=('serial','nunique'),french=('french','mean')).to_csv(OUT/'french_british.csv')

fig,ax=plt.subplots(figsize=(8,4.8))
eligible=local[local.households>=10]
ax.hist(eligible.maternal*100,bins=np.arange(0,110,10),color='#365c75',edgecolor='white')
ax.set(xlabel="Children matching the woman's origin (mean of household shares, %)",ylabel='Census localities',
 title='One census, divergent local patterns of origin recording')
ax.spines[['top','right']].set_visible(False)
fig.text(.12,.01,f'1881; five European origin groups; {len(eligible):,} localities with ≥10 inferred mixed-origin families.',fontsize=9)
fig.tight_layout(rect=[0,.045,1,1]);fig.savefig(OUT/'local_patterns.png',dpi=200);plt.close(fig)

counts={
 'source_rows':c.execute('select count(*) from persons').fetchone()[0],
 'kept_rows':c.execute("select count(*) from persons where remove_TCP='0'").fetchone()[0],
 'candidate_households':c.execute('select count(*) from family_candidates').fetchone()[0],
 'strict_households':d.serial.nunique(),'strict_children':len(d),
 'mixed_households':len(hh),'mixed_children':len(mixed),
 'mixed_child_maternal':int(mixed.maternal.sum()),'mixed_child_paternal':int(mixed.paternal.sum()),
 'mixed_household_maternal_mean':hh.maternal.mean(),'mixed_household_paternal_mean':hh.paternal.mean(),
 'eligible_localities':len(eligible),'localities_ge90_maternal':int(eligible.maternal.ge(.9).sum()),
 'localities_le10_maternal':int(eligible.maternal.le(.1).sum()),
 'eligible_enumeration_units':int(units.households.ge(10).sum()),
 'enumeration_units_ge90_maternal':int((units.households.ge(10)&units.maternal.ge(.9)).sum()),
}
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()
manifest={'source':str(SOURCE),'source_bytes':SOURCE.stat().st_size,'source_sha256':sha(SOURCE),
 'labels_sha256':sha(LABELS),'dataset_doi':'10.5683/SP3/FXZEVO','duckdb_version':duckdb.__version__,
 'counts':{k:int(v) if isinstance(v,np.integer) else v for k,v in counts.items()}}
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest['counts'],indent=2),flush=True)
print(eligible.sort_values('maternal',ascending=False).head(20).to_string(index=False),flush=True)
c.close()
