#!/usr/bin/env python3
"""Render the campaign architecture and its standalone Mermaid source from one graph."""
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT=Path(__file__).resolve().parents[1]
NODES={
 'campaign':('Campaign selection',.5,.94),
 'experiments':('Experiment bundles',.18,.81),
 'profiles':('Hardware and deployments',.82,.81),
 'plan':('Resolved job plan',.5,.68),
 'scheduler':('Scheduler and reservations',.5,.54),
 'local':('Local worker',.23,.40),
 'remote':('SSH worker',.77,.40),
 'records':('Raw results and provenance',.5,.26),
 'reports':('Report and charts',.25,.10),
 'pr':('Results branch and PR',.77,.10),
}
EDGES=[('campaign','plan'),('experiments','plan'),('profiles','plan'),('plan','scheduler'),
       ('scheduler','local'),('scheduler','remote'),('local','records'),('remote','records'),('records','reports'),('reports','pr')]
fig,ax=plt.subplots(figsize=(11,10));ax.set_xlim(0,1);ax.set_ylim(0,1);ax.axis('off')
for a,b in EDGES:
 _,x1,y1=NODES[a];_,x2,y2=NODES[b]
 if abs(y1-y2)<.01: start=(x1+.16,y1);end=(x2-.16,y2)
 else:start=(x1,y1-.029);end=(x2,y2+.035)
 ax.annotate('',xy=end,xytext=start,arrowprops={'arrowstyle':'->','color':'#64748b','lw':1.7},zorder=1)
for label,x,y in NODES.values():
 ax.add_patch(FancyBboxPatch((x-.16,y-.028),.32,.056,boxstyle='round,pad=0.009',facecolor='#edf4fc',edgecolor='#3265a8',linewidth=1.4,zorder=2))
 ax.text(x,y,label,ha='center',va='center',fontsize=11,color='#173452',zorder=3)
fig.tight_layout();fig.savefig(ROOT/'diagrams/campaign-architecture.png',dpi=150,metadata={'Software':'llm-eval'});plt.close(fig)
source='# Campaign architecture\n\n```mermaid\nflowchart TD\n'
for key,(label,_,_) in NODES.items():source+=f'  {key}["{label}"]\n'
for a,b in EDGES:source+=f'  {a} --> {b}\n'
(ROOT/'diagrams/campaign-architecture.md').write_text(source+'```\n',encoding='utf-8')
