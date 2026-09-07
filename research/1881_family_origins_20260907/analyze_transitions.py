"""Page-boundary tests, using the retained child-level output of analyze.py."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results'
d=pd.read_csv(OUT/'mixed_triads.csv.gz',dtype={'serial':str})
d=d.sort_values(['serial','child_page','child_line','child_id'])
g=d.groupby('serial',sort=False)
for col in ['corigin','child_page','child_line','sex','child_age','child_url','cb','clean_codes']:
    d['prev_'+col]=g[col].shift()
d['ordinal']=g.cumcount()+1
x=d[d.prev_corigin.notna()].copy()
x['pagebreak']=x.child_page.ne(x.prev_child_page)
x['origin_change']=x.corigin.ne(x.prev_corigin)
x['maternal_to_paternal']=x.prev_corigin.eq(x.morigin)&x.corigin.eq(x.forigin)
x['paternal_to_maternal']=x.prev_corigin.eq(x.forigin)&x.corigin.eq(x.morigin)
x['same_sex']=x.sex.eq(x.prev_sex)
x['age_gap']=x.prev_child_age-x.child_age
x['same_birthplace']=x.cb.eq(x.prev_cb)&x.cb.notna()
x['ordinary_boundary']=~x.pagebreak | (x.child_page.eq(x.prev_child_page+1)&x.child_line.eq(1)&x.prev_child_line.eq(25))
x['same_image']=x.child_url.eq(x.prev_child_url)
x.to_csv(OUT/'sibling_transitions.csv.gz',index=False)

tables=[]
for name, mask in [('all',np.ones(len(x),dtype=bool)),('same sex',x.same_sex),
 ('both child origins classified',x.corigin.ne('Other/missing')&x.prev_corigin.ne('Other/missing')),
 ('same recorded birthplace',x.same_birthplace),('no origin flags/secondary codes',x.clean_codes & x.prev_clean_codes.eq(True)),
 ('consecutive pages, lines 25 to 1',x.ordinary_boundary),('same digital image',x.same_image),
 ('both children age 2 or older',x.child_age.ge(2)&x.prev_child_age.ge(2)),
 ('descending ages, gap <= 4',x.age_gap.between(0,4))]:
 for boundary,z in x[mask].groupby('pagebreak'):
  tables.append(dict(specification=name,pagebreak=bool(boundary),pairs=len(z),households=z.serial.nunique(),
   changes=int(z.origin_change.sum()),change_rate=z.origin_change.mean(),
   previous_maternal=int(z.prev_corigin.eq(z.morigin).sum()),
   maternal_to_paternal=int(z.maternal_to_paternal.sum()),paternal_to_maternal=int(z.paternal_to_maternal.sum())))
pd.DataFrame(tables).to_csv(OUT/'page_boundary_tests.csv',index=False)
x.groupby('child_line').agg(pairs=('child_id','size'),changes=('origin_change','sum'),rate=('origin_change','mean')).to_csv(OUT/'line_transition_rates.csv')

# Comparison is within the same inferred family, requiring both kinds of transition.
paired=x.groupby(['serial','pagebreak']).origin_change.mean().unstack().dropna()
paired.columns=['same_page','new_page']
paired['difference']=paired.new_page-paired.same_page
paired.to_csv(OUT/'within_family_page_contrasts.csv')

# Cluster-resampled uncertainty for this descriptive within-family difference.
# It does not cover transcription or genealogical uncertainty.
mapping=x.drop_duplicates('serial').set_index('serial').enumeration_unit
paired['unit']=mapping.reindex(paired.index)
a=paired.groupby('unit').difference.agg(['sum','count']).to_numpy()
rng=np.random.default_rng(1881)
boot=[]
for _ in range(2000):
    z=a[rng.integers(0,len(a),len(a))]
    boot.append(z[:,0].sum()/z[:,1].sum())

# A within-family diagnostic permutation: put its existing boundary at another
# sibling transition. This holds outcomes and family membership fixed. It is
# deliberately labelled diagnostic, not a randomized historical experiment.
eligible=x[x.serial.isin(paired.index)]
groups=[z.origin_change.to_numpy(dtype=float) for _,z in eligible.groupby('serial')]
assert all(z.pagebreak.sum()==1 for _,z in eligible.groupby('serial'))
stats=[]
for _ in range(2000):
    chosen=np.array([v[rng.integers(len(v))] for v in groups])
    same=np.array([(v.sum()-picked)/(len(v)-1) for v,picked in zip(groups,chosen)])
    stats.append(np.mean(chosen-same))
observed=paired.difference.mean()
summary=dict(pairs=len(x),pagebreak_pairs=int(x.pagebreak.sum()),
 within_family_households=len(paired),within_family_same_page_mean=paired.same_page.mean(),
 within_family_pagebreak_mean=paired.new_page.mean(),within_family_difference=observed,
 cluster_bootstrap_95_interval=np.quantile(boot,[.025,.975]).tolist(),
 diagnostic_permutations=2000,diagnostic_permutation_p=(1+sum(v>=observed for v in stats))/2001,
 diagnostic_permutation_95_interval=np.quantile(stats,[.025,.975]).tolist())
(OUT/'page_boundary_summary.json').write_text(json.dumps(summary,indent=2)+'\n')

# Can other kinds of mixed families in the same unit predict the held-out pair?
h=pd.read_csv(OUT/'mixed_households.csv',dtype={'serial':str})
h['pair']=h.forigin+' / '+h.morigin
s=h.groupby('enumeration_unit').maternal.transform('sum')
n=h.groupby('enumeration_unit').maternal.transform('size')
ps=h.groupby(['enumeration_unit','pair']).maternal.transform('sum')
pn=h.groupby(['enumeration_unit','pair']).maternal.transform('size')
h['other_pair_n']=n-pn;h['other_pair_maternal']=(s-ps)/(n-pn)
pred=[]
for low,high,label in [(0,.1,'<=10% maternal in other origin pairings'),(.9,1.00001,'>=90% maternal in other origin pairings')]:
 z=h[h.other_pair_n.ge(5)&h.other_pair_maternal.ge(low)&h.other_pair_maternal.le(high)]
 pred.append(dict(comparison=label,households=len(z),units=z.enumeration_unit.nunique(),maternal=z.maternal.mean(),paternal=z.paternal.mean()))
pd.DataFrame(pred).to_csv(OUT/'other_origin_pair_prediction.csv',index=False)

fig,axs=plt.subplots(1,2,figsize=(9,4.6))
base=pd.DataFrame(tables).query("specification=='all'")
axs[0].bar(['Within a page','Across a page'],base.change_rate*100,color=['#365c75','#b05d3e'])
axs[0].set(ylabel='Adjacent children with different recorded origins (%)',title='All adjacent child pairs')
axs[1].bar(['Within a page','Across a page'],[paired.same_page.mean()*100,paired.new_page.mean()*100],color=['#365c75','#b05d3e'])
axs[1].set(title=f'Within the same {len(paired):,} families')
for ax in axs:
 ax.spines[['top','right']].set_visible(False)
 for patch in ax.patches:
  ax.text(patch.get_x()+patch.get_width()/2,patch.get_height()+.15,f'{patch.get_height():.2f}%',ha='center',fontsize=10)
 ax.set_ylim(0,10)
fig.text(.08,.015,'1881 census; inferred simple families; French, English, Irish, Scottish and German parental origins.',fontsize=9)
fig.tight_layout(rect=[0,.06,1,1]);fig.savefig(OUT/'page_boundary.png',dpi=200);plt.close(fig)
print(json.dumps(summary,indent=2))
print(pd.DataFrame(tables).to_string(index=False))
print(pd.DataFrame(pred).to_string(index=False))
