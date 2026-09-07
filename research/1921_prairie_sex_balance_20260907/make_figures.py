from pathlib import Path
import csv
import os
os.environ.setdefault('MPLCONFIGDIR', '/tmp/prairie1921-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
rows = list(csv.DictReader((HERE/'ratios.csv').open()))
plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':10,
                     'axes.spines.top':False, 'axes.spines.right':False})
groups = ['All', 'Canadian-born', 'British-born', 'Foreign-born']
fig, axs = plt.subplots(1, 4, figsize=(12, 4.2), sharey=True)
fig.subplots_adjust(left=.13,right=.99,bottom=.17,top=.76,wspace=.12)
for ax, province in zip(axs, ['MB','SK','AB','Prairies']):
    for y,g in enumerate(groups):
        a = next(float(r['males_per_100_females']) for r in rows if r['province']==province and r['area']=='Cities' and r['birthplace']==g)
        b = next(float(r['males_per_100_females']) for r in rows if r['province']==province and r['area']=='Remainder' and r['birthplace']==g)
        ax.plot([a,b],[y,y],color='#bdc6cc',lw=2,zorder=1)
        ax.scatter(a,y,color='#19657d',s=46,label='Cities' if y==0 else None,zorder=3)
        ax.scatter(b,y,color='#bc562d',s=46,marker='s',label='Remainder' if y==0 else None,zorder=3)
    ax.axvline(100,color='#777',ls=':',lw=1)
    ax.set_title({'MB':'Manitoba','SK':'Saskatchewan','AB':'Alberta','Prairies':'Pooled Prairies'}[province])
    ax.set_xlim(88,154)
    ax.set_xticks([100,120,140])
    ax.set_yticks(range(4),groups)
    ax.grid(axis='x',alpha=.13)
axs[0].invert_yaxis()
handles, names = axs[-1].get_legend_handles_labels()
fig.legend(handles,names,loc='upper center',bbox_to_anchor=(.56,.91),ncol=2,frameon=False,fontsize=10)
fig.supxlabel('Males per 100 females, all ages, 1921',y=.025)
fig.suptitle('The city–remainder difference persists within each birthplace group',fontsize=13)
fig.savefig(HERE/'sex_ratios.png',dpi=200)
fig.savefig(HERE/'sex_ratios.pdf')
plt.close(fig)

rows=list(csv.DictReader((HERE/'decomposition.csv').open()))
fig,ax=plt.subplots(figsize=(8,4.2),layout='constrained')
colors=['#19657d','#5190a1','#a4c9ce','#bc562d']
fields=['Canadian-born_within_pp','British-born_within_pp','Foreign-born_within_pp','composition_pp']
labels=['Within Canadian-born','Within British-born','Within foreign-born','Birthplace composition']
for y,r in enumerate(rows):
    positive=negative=0
    for field,label,color in zip(fields,labels,colors):
        v=float(r[field]);left=positive if v>=0 else negative
        ax.barh(y,v,left=left,color=color,height=.55,label=label if y==0 else None)
        if v>=0:positive+=v
        else:negative+=v
    ax.plot(float(r['gap_pp']),y,'|',color='black',markersize=19,markeredgewidth=2)
ax.axvline(0,color='#666',lw=.8)
ax.set_yticks(range(4),['Manitoba','Saskatchewan','Alberta','Pooled Prairies'])
ax.invert_yaxis()
ax.set_xlabel('Difference in male population share: remainder minus cities (percentage points)')
ax.set_title('Birthplace composition contributes little to the observed difference',pad=15)
ax.legend(loc='upper center',bbox_to_anchor=(.5,-.20),ncol=2,frameon=False,fontsize=9)
fig.savefig(HERE/'decomposition.png',dpi=200,bbox_inches='tight')
fig.savefig(HERE/'decomposition.pdf',bbox_inches='tight')
plt.close(fig)
