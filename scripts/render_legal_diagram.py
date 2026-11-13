#!/usr/bin/env python3
"""Render the legal benchmark stages and their explicit outputs, and the standalone Mermaid source, from one graph."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT=Path(__file__).resolve().parents[1]
# Stages (blue) and the explicit outputs they write (grey). The next stage names an output file in its case: a phase
# dependency only orders jobs. Stage 3 is optional; the frozen evaluation takes from it at most the calibration file.
NODES={
 'offload':('1. Offload calibration\nmodel-offloading category-smoke',.18,.92,True),
 'attempt':('One succeeded offload\nattempt directory',.50,.92,False),
 'profile':('2. Locked serving profile\nprofiles freeze (placement attested)',.18,.76,True),
 'locked':('serving-profile.json\nand its SHA-256',.50,.76,False),
 'routing':('3. Routing calibration and replay\n(optional): legal-benchmark generation\nruns per recipe, routed and fallback',.82,.60,True),
 'calibration':('routing calibrate:\ncalibration file (optional)',.50,.44,False),
 'replay':('routing export, replay, verify:\nrouting suite, replay manifest,\nsidecar (local only)',.82,.44,False),
 'evaluation':('4. Frozen legal evaluation\nretrieval, generation, workflow',.18,.28,True),
 'manifest':('Attempts, private local/ detail,\noutput-manifest.json',.50,.28,False),
 'score':('score in a later campaign\n(names the output manifest)',.82,.28,True),
 'report':('5. Local report\nllm-eval report (projection)',.50,.10,True),
 'bundle':('Projected local bundle;\nno publication',.82,.10,False),
}
EDGES=[('offload','attempt'),('attempt','profile'),('profile','locked'),('locked','evaluation'),('locked','routing'),
       ('routing','calibration'),('routing','replay'),('calibration','evaluation'),('evaluation','manifest'),('manifest','score'),
       ('evaluation','report'),('score','report'),('report','bundle')]
OPTIONAL={('calibration','evaluation')}      # drawn dashed: used only when a selector threshold is used
W,H=.26,.10


def edge_point(x,y,tx,ty):
    """Where the line from a box centre towards (tx, ty) leaves the box."""
    dx,dy=tx-x,ty-y
    t=min((W/2+.008)/abs(dx) if dx else 9,(H/2+.008)/abs(dy) if dy else 9)
    return x+dx*t,y+dy*t


fig,ax=plt.subplots(figsize=(13,11));ax.set_xlim(0,1);ax.set_ylim(0,1);ax.axis('off')
for a,b in EDGES:
 _,x1,y1,_=NODES[a];_,x2,y2,_=NODES[b]
 ax.annotate('',xy=edge_point(x2,y2,x1,y1),xytext=edge_point(x1,y1,x2,y2),zorder=1,
             arrowprops={'arrowstyle':'->','color':'#64748b','lw':1.7,'linestyle':'--' if (a,b) in OPTIONAL else '-'})
for label,x,y,stage in NODES.values():
 ax.add_patch(FancyBboxPatch((x-W/2,y-H/2),W,H,boxstyle='round,pad=0.008',facecolor='#edf4fc' if stage else '#f5f5f4',
                             edgecolor='#3265a8' if stage else '#78716c',linewidth=1.4,zorder=2))
 ax.text(x,y,label,ha='center',va='center',fontsize=10,color='#173452' if stage else '#292524',zorder=3)
ax.text(.5,.995,'Outputs are passed by naming the file in the next case; dashed: only with a selector threshold. '
        'Fictional fixture suites only; host measurements are pending.',ha='center',va='top',fontsize=9.5,color='#475569')
fig.tight_layout();fig.savefig(ROOT/'diagrams/legal-benchmark-workflow.png',dpi=150,metadata={'Software':'llm-eval'});plt.close(fig)
source=('# Legal benchmark workflow\n\nThe five stages of the [legal benchmark walkthrough](../docs/LEGAL_BENCHMARK_WALKTHROUGH.md) and the explicit '
        'output of each. A phase dependency only orders jobs; the next stage names the output file in its case. Stage 3 is '
        'optional, and the frozen evaluation takes from it at most the calibration file (dashed edge).\n\n```mermaid\nflowchart TD\n')
for key,(label,_,_,_) in NODES.items():source+='  '+key+'["'+label.replace('\n',' ')+'"]\n'
for a,b in EDGES:source+=f'  {a} {"-.->" if (a,b) in OPTIONAL else "-->"} {b}\n'
(ROOT/'diagrams/legal-benchmark-workflow.md').write_text(source+'```\n\n[View PNG rendering](legal-benchmark-workflow.png).\n',encoding='utf-8',newline='\n')
