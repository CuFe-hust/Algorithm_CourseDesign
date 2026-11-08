"""Publication-style Matplotlib figures from saved results; no fitting or database access.

Optional offline plotting dependency: matplotlib. It is not a product dependency.
"""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/analysis/experiments/difficulty-v1'
rows=json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
colors={'B0':'#72767c','D0':'#c78228','Fixed':'#6d62a7','D1':'#087d8c'}
scenarios=['difficulty_signal','mislabeled_teacher','sparse','mnar','no_difficulty','nonlinear_mismatch']
labels=['Difficulty signal','Noisy teacher labels','Sparse observations','MNAR missingness','No true difficulty','Nonlinear mismatch']
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':15,'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(2,1,figsize=(16,9),gridspec_kw={'height_ratios':[1.55,1]})
for ax,task,subset,names in [(axes[0],'known_item',scenarios,labels),
                            (axes[1],'unseen_item',scenarios[:2],labels[:2])]:
    for offset,(model,color) in enumerate(colors.items()):
        values=[next(r for r in rows if r['task']==task and r['scenario']==s and r['model']==model) for s in subset]
        x=[i+(offset-1.5)*.13 for i in range(len(subset))]
        ax.errorbar(x,[r['rmse_mean'] for r in values],yerr=[r['rmse_sd'] for r in values],
                    fmt='o',capsize=4,color=color,label=model,markersize=7,elinewidth=1.7)
    ax.set_xticks(range(len(subset)),names)
    ax.set_ylabel('Held-out RMSE')
    ax.set_ylim(0,.39)
    ax.grid(axis='y',alpha=.22)
    ax.set_axisbelow(True)
    ax.set_title('A. Unobserved responses to previously observed items' if task=='known_item'
                 else 'B. Entirely unseen items (no response-based item calibration)',loc='left',fontsize=17,pad=12)
axes[0].axvspan(3.6,4.4,color='#f8e1e0',zorder=-1)
axes[0].text(4,.045,'D1 loses to B0',ha='center',fontsize=12,color='#a13832')
axes[0].legend(ncol=4,loc='upper right',frameon=False)
fig.suptitle('Difficulty-aware fractional score prediction: all final stress scenarios',fontsize=21,y=.98)
fig.text(.5,.025,'80 synthetic learners × 66 items × 11 chapters; six independent datasets/scenario.\n'
         'Lower RMSE is better. Error bars: one dataset SD, not confidence intervals for human abilities.',
         ha='center',fontsize=12,color='#45505c')
fig.subplots_adjust(left=.075,right=.98,top=.91,bottom=.14,hspace=.55)
for suffix in ('png','svg'):
    fig.savefig(OUT/f'difficulty-model-validation.{suffix}',dpi=240,facecolor='white')
    if suffix=='svg':
        svg=OUT/'difficulty-model-validation.svg'
        svg.write_text('\n'.join(line.rstrip() for line in svg.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8')
plt.close(fig)
print('Saved difficulty-model-validation.png (3840x2160) and SVG from frozen summary.json')
