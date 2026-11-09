"""Summary charts over published results: one figure per experiment and hardware configuration.

Each figure compares the ranked harness and model combinations of one experiment on one hardware configuration.
Models are rows, harnesses are colors, and every measure has its own panel and its own axis.
"""
from __future__ import annotations

from pathlib import Path

# Categorical slots are assigned by harness name, never by rank, so a harness keeps its color in every figure.
HARNESS_COLORS = {'ollama': '#2a78d6', 'koboldcpp': '#eb6834', 'lmstudio': '#1baf7a'}
SPARE_COLORS = ('#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948')
OTHER_COLOR = '#898781'
SURFACE, INK, SECONDARY, MUTED, GRID, AXIS = '#fcfcfb', '#0b0b0b', '#52514e', '#898781', '#e1e0d9', '#c3c2b7'

PANELS = (
    # (title, value, label, log scale)
    ('Checks passed (%)', lambda r: 100 * r['score'][0] / r['score'][1], lambda r: f"{r['score'][0]}/{r['score'][1]}", False),
    ('Median wall time (s, log scale)', lambda r: r['wall_mid'], lambda r: f"{r['wall_mid']:.3g}", True),
    ('Peak backend RAM (GiB)', lambda r: r.get('backend_rss_gib'), lambda r: f"{r['backend_rss_gib']:.1f}", False),
    ('Peak GPU memory (GiB)', lambda r: r.get('gpu_gib'), lambda r: f"{r['gpu_gib']:.1f}", False),
)


def harness_colors(harnesses):
    """Fixed color per known harness; unknown ones take the spare slots in name order, then a shared gray."""
    spare = iter(SPARE_COLORS)
    return {h: HARNESS_COLORS.get(h) or next(spare, OTHER_COLOR) for h in sorted(harnesses)}


def available():
    try:
        import matplotlib      # noqa: F401
    except ImportError:
        return False
    return True


def summary_chart(records, path, title):
    """Draw `records` (ranked, one per harness and model combination) to `path`; returns the panel titles drawn."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

    panels = [p for p in PANELS if any(p[1](r) is not None for r in records)]
    models = list(dict.fromkeys(r['model'] for r in records))      # best-ranked model first
    colors = harness_colors({r['harness'] for r in records})
    rows, ticks, y = [], [], 0.0
    for model in models:
        group = sorted((r for r in records if r['model'] == model), key=lambda r: r['harness'])
        ticks.append((y + (len(group) - 1) / 2, model))
        for r in group:
            rows.append((y, r))
            y += 1
        y += 0.7      # air between models
    with plt.rc_context({'font.family': 'DejaVu Sans', 'font.size': 11, 'text.color': INK, 'axes.labelcolor': SECONDARY,
                         'xtick.color': MUTED, 'ytick.color': INK, 'axes.edgecolor': AXIS}):
        fig, axes = plt.subplots(1, len(panels), sharey=True, figsize=(12, max(2.4, 1.3 + 0.24 * y)), facecolor=SURFACE,
                                 layout='constrained', squeeze=False)
        for ax, (name, value, label, log) in zip(axes[0], panels):
            ax.set_facecolor(SURFACE)
            points = [(pos, r, value(r)) for pos, r in rows if value(r) is not None]
            values = [v for _, _, v in points]
            if log:
                # A bar has no honest length on a log axis, so position alone carries the value.
                ax.set_xscale('log')
                ax.set_xlim(min(values) / 1.8, max(values) * 4)
                # Label 1-2-5 steps on a narrow range; whole decades once the range is wide enough to crowd them.
                ax.xaxis.set_major_locator(LogLocator(subs=(1,) if max(values) > 50 * min(values) else (1, 2, 5)))
                ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: format(v, 'g')))
                ax.xaxis.set_minor_formatter(NullFormatter())
                for pos, r, v in points:
                    ax.plot(v, pos, 'o', color=colors[r['harness']], markersize=7, markeredgecolor=SURFACE, markeredgewidth=1.5)
                    ax.annotate(label(r), (v, pos), xytext=(7, 0), textcoords='offset points', va='center', fontsize=9, color=SECONDARY)
            else:
                ax.set_xlim(0, max(values) * 1.22 if max(values) > 0 else 1)
                if name.endswith('(%)'):
                    ax.set_xlim(0, 122)
                    ax.set_xticks(range(0, 101, 25))
                ax.barh([pos for pos, _, _ in points], values, height=0.62, color=[colors[r['harness']] for _, r, _ in points])
                for pos, r, v in points:
                    ax.annotate(label(r), (v, pos), xytext=(4, 0), textcoords='offset points', va='center', fontsize=9, color=SECONDARY)
            ax.set_title(name, loc='left', fontsize=11, color=INK)
            ax.grid(axis='x', color=GRID, linewidth=0.8)
            ax.set_axisbelow(True)
            ax.tick_params(length=0, which='both', labelsize=9)
            for side in ('top', 'right', 'bottom'):
                ax.spines[side].set_visible(False)
        axes[0][0].set_yticks([pos for pos, _ in ticks], [name for _, name in ticks], fontsize=10)
        axes[0][0].set_ylim(y - 0.2, -0.8)
        fig.suptitle(title, x=0.01, ha='left', fontsize=12, color=INK)
        fig.legend(handles=[Patch(color=c, label=h) for h, c in colors.items()], loc='outside upper right', ncols=len(colors),
                   frameon=False, fontsize=9, title='Harness', title_fontsize=9, alignment='right')
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=160, facecolor=SURFACE, metadata={'Software': 'llm-eval'})
        plt.close(fig)
    return [p[0] for p in panels]
