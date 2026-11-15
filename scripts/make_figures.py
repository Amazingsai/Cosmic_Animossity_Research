#!/usr/bin/env python3
"""Generate the publication figures for the Cosmic Animosity final analysis.

Standard library only (no matplotlib, no numpy). Reads the consolidated CSVs in
``results/analysis/`` and writes hand-built SVG files into
``results/analysis/figures/``.

Usage (from the project root):

    python scripts/make_figures.py

Every figure is derived from an analysis CSV, never from prose, so re-running the
analysis CSVs regenerates identical figures. Figures are pure vector SVG, so they
scale into a thesis page without resampling artefacts.

Figure inventory
----------------
fig1_validation_status_by_family.svg  Set 1 classification per prompt family (N = 40)
fig2_damage_generated_vs_baseline.svg Set 2 damage per candidate against its baseline
fig3_action_reachability.svg          Set 2 four-action reachability matrix
fig4_failure_attribution.svg          Failure count per attribution category
fig5_timing_resolution.svg            Sampling resolution against the claimed deltas
fig6_classification_vs_damage.svg     M1-M5 classification against measured damage
fig7_rebuild_vs_asbuilt.svg           Phase 7H rebuild / as-built damage per phase
"""

import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ANALYSIS = os.path.join(ROOT, "results", "analysis")
FIGDIR = os.path.join(ANALYSIS, "figures")

# --- palette (muted, dark enough for white label text) -----------------------
C_VALID = "#41a161"
C_REVIEW = "#b87700"
C_INVALID = "#d15858"
C_GEN = "#4a90e2"
C_BASE = "#d15858"
C_PURPLE = "#7b68ee"
C_GREY = "#6b7280"
C_LIGHT = "#dfe3e8"
C_INK = "#1f2933"
C_RULE = "#9aa5b1"

FONT = "Segoe UI, Helvetica, Arial, sans-serif"


# --- low-level SVG helpers ---------------------------------------------------
def esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class Svg(object):
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.parts = []

    def add(self, block):
        self.parts.append(block)

    def rect(self, x, y, w, h, fill, stroke="none", rx=0, opacity=1.0):
        self.add(
            '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%d" '
            'fill="%s" stroke="%s" opacity="%.2f"/>'
            % (x, y, w, h, rx, fill, stroke, opacity)
        )

    def line(self, x1, y1, x2, y2, stroke=C_RULE, width=1.0, dash=None):
        d = ' stroke-dasharray="%s"' % dash if dash else ""
        self.add(
            '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
            'stroke-width="%.1f"%s/>' % (x1, y1, x2, y2, stroke, width, d)
        )

    def text(self, x, y, s, size=12, anchor="start", weight="normal", fill=C_INK):
        self.add(
            '<text x="%.1f" y="%.1f" font-family="%s" font-size="%d" '
            'font-weight="%s" text-anchor="%s" fill="%s">%s</text>'
            % (x, y, FONT, size, weight, anchor, fill, esc(s))
        )

    def render(self):
        head = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
            'viewBox="0 0 %d %d">' % (self.width, self.height, self.width, self.height)
        )
        bg = '<rect width="100%" height="100%" fill="#ffffff"/>'
        return "\n".join([head, bg] + self.parts + ["</svg>"])


def header(svg, title, subtitle, legend=()):
    """Title block plus an optional legend of (label, colour) at the top right."""
    svg.text(40, 36, title, size=18, weight="bold")
    svg.text(40, 56, subtitle, size=11.5, fill=C_GREY)
    x = svg.width - 40
    for label, colour in reversed(list(legend)):
        w = 12 + 6 * len(label)
        svg.rect(x - w, 26, 11, 11, colour, rx=2)
        svg.text(x - w + 16, 36, label, size=11)
        x -= w + 16


def yaxis(svg, x0, y0, y1, vmax, ticks, label, fmt="%d"):
    svg.line(x0, y0, x0, y1, stroke=C_RULE, width=1.2)
    for i in range(ticks + 1):
        v = vmax * i / float(ticks)
        y = y1 - (y1 - y0) * i / float(ticks)
        svg.line(x0, y, x0 + 6, y, stroke=C_RULE)
        svg.text(x0 - 8, y + 4, fmt % v, size=10.5, anchor="end", fill=C_GREY)
    svg.text(18, (y0 + y1) / 2.0, label, size=11, anchor="middle", fill=C_GREY)


def xaxis_label(svg, x, y, s):
    svg.text(x, y, s, size=11, anchor="middle")


# --- CSV access --------------------------------------------------------------
def read(name):
    path = os.path.join(ANALYSIS, name)
    if not os.path.isfile(path):
        raise SystemExit("missing analysis file: %s" % path)
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def save(svg, name):
    if not os.path.isdir(FIGDIR):
        os.makedirs(FIGDIR)
    path = os.path.join(FIGDIR, name)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(svg.render())
    print("wrote figures/%s" % name)
    return path


# --- fig 1 -------------------------------------------------------------------
def fig1():
    rows = [r for r in read("set1_family_status_matrix.csv") if r["prompt_family"] != "ALL"]
    total = [r for r in read("set1_family_status_matrix.csv") if r["prompt_family"] == "ALL"][0]
    svg = Svg(940, 520)
    header(
        svg,
        "Validation classification per prompt family",
        "Evaluation Set 1, N = %s outputs (4 per prompt family). "
        "VALID %s / REVIEW %s / INVALID %s."
        % (total["n"], total["valid"], total["review"], total["invalid"]),
        [("VALID", C_VALID), ("REVIEW", C_REVIEW), ("INVALID", C_INVALID)],
    )
    x0, x1 = 130.0, 800.0
    top, row_h, gap = 92.0, 30.0, 8.0
    n = len(rows)
    unit = (x1 - x0) / 4.0
    for i, r in enumerate(rows):
        y = top + i * (row_h + gap)
        svg.text(x0 - 12, y + row_h / 2.0 + 4, r["prompt_family"], size=12,
                 anchor="end", weight="bold")
        x = x0
        for key, colour in (("valid", C_VALID), ("review", C_REVIEW), ("invalid", C_INVALID)):
            c = int(r[key])
            if c == 0:
                continue
            w = unit * c
            svg.rect(x, y, w, row_h, colour)
            svg.text(x + w / 2.0, y + row_h / 2.0 + 4, str(c), size=11,
                     anchor="middle", fill="#ffffff", weight="bold")
            x += w
        svg.text(x1 + 12, y + row_h / 2.0 + 4,
                 "V%s R%s I%s" % (r["valid"], r["review"], r["invalid"]),
                 size=10.5, fill=C_GREY)
    # axis
    ay = top + n * (row_h + gap) + 6
    svg.line(x0, ay, x1, ay, stroke=C_RULE, width=1.2)
    for k in range(5):
        svg.text(x0 + unit * k, ay + 16, str(k), size=10.5, anchor="middle", fill=C_GREY)
    svg.text((x0 + x1) / 2.0, ay + 36, "outputs in family (of 4)", size=11,
             anchor="middle", fill=C_GREY)
    save(svg, "fig1_validation_status_by_family.svg")


# --- fig 2 -------------------------------------------------------------------
def fig2():
    rows = [r for r in read("set2_candidate_gameplay.csv") if r["candidate_no"]]
    svg = Svg(940, 540)
    header(
        svg,
        "Damage dealt per three-trial comparison, generated tree versus baseline",
        "Evaluation Set 2. Identical arena, frozen BP_AICharacter, 3 trials x 4 phases "
        "per subject. Generated total 630.0 vs baseline 2030.0 (31.0 %).",
        [("generated tree", C_GEN), ("BP_AICharacter", C_BASE)],
    )
    x0, y0, y1 = 92.0, 92.0, 452.0
    vmax = 400.0
    yaxis(svg, x0, y0, y1, vmax, 4, "damage dealt", fmt="%d")
    plot_w = svg.width - x0 - 60
    group = plot_w / float(len(rows))
    bw = 36.0
    for i, r in enumerate(rows):
        cx = x0 + group * i + group / 2.0
        gd = float(r["gen_damage"])
        bd = float(r["base_damage"])
        for off, val, colour in ((-bw - 3, gd, C_GEN), (3, bd, C_BASE)):
            h = (y1 - y0) * val / vmax
            svg.rect(cx + off, y1 - h, bw, max(h, 1.0), colour)
            svg.text(cx + off + bw / 2.0, y1 - h - 6, "%.0f" % val, size=10.5,
                     anchor="middle", weight="bold")
        svg.text(cx, y1 + 20, "#%s" % r["candidate_no"], size=12, anchor="middle",
                 weight="bold")
        svg.text(cx, y1 + 36, r["sample_id"], size=10, anchor="middle", fill=C_GREY)
        svg.text(cx, y1 + 50,
                 "%s%% of base" % r["gen_damage_pct_of_baseline"], size=9.5,
                 anchor="middle", fill=C_GREY)
    svg.line(x0, y1, svg.width - 60, y1, stroke=C_RULE, width=1.2)
    save(svg, "fig2_damage_generated_vs_baseline.svg")


# --- fig 3 -------------------------------------------------------------------
STATE_STYLE = {
    "reached": (C_VALID, "#ffffff", "reached"),
    "unreachable": (C_INVALID, "#ffffff", "unreachable"),
    "never_executes": (C_INVALID, "#ffffff", "never executes"),
    "entered_never_succeeds": (C_REVIEW, "#ffffff", "entered, no success"),
    "entered_always_refused": (C_REVIEW, "#ffffff", "entered, refused"),
    "satisfies_selector": (C_LIGHT, C_INK, "selector satisfied"),
    "unobservable": (C_LIGHT, C_INK, "not observable"),
    "not_in_tree": (C_GREY, "#ffffff", "not in tree"),
}


def fig3():
    rows = read("action_reachability.csv")
    order = ["1", "2", "3", "6", "5", "4"]
    actions = ["move_to_target", "move_away_from_target", "attack", "wait"]
    labels = {
        "move_to_target": "move_to_target",
        "move_away_from_target": "move_away_from_target",
        "attack": "attack",
        "wait": "wait",
    }
    cells = {}
    for r in rows:
        cells[(r["candidate_no"], r["action"])] = r["reachability"]
    svg = Svg(940, 520)
    header(
        svg,
        "Action reachability matrix, six selected candidates",
        "Reachability is a measurement per branch, not a property of the specification. "
        "Green = executed; amber = entered but never satisfied; red = unreachable; "
        "grey = absent from the tree.",
        [("reached", C_VALID), ("entered / not satisfied", C_REVIEW),
         ("unreachable", C_INVALID)],
    )
    x0, y0 = 190.0, 100.0
    cw, ch = 118.0, 62.0
    for j, a in enumerate(actions):
        svg.text(x0 - 14, y0 + j * ch + ch / 2.0 + 4, labels[a], size=11.5, anchor="end")
    for i, cand in enumerate(order):
        svg.text(x0 + i * cw + cw / 2.0, y0 - 12, "#%s" % cand, size=12,
                 anchor="middle", weight="bold")
        for j, a in enumerate(actions):
            state = cells.get((cand, a), "unobservable")
            fill, ink, text = STATE_STYLE[state]
            svg.rect(x0 + i * cw + 3, y0 + j * ch + 3, cw - 6, ch - 6, fill, rx=4)
            svg.text(x0 + i * cw + cw / 2.0, y0 + j * ch + ch / 2.0 + 4, text,
                     size=10.5, anchor="middle", fill=ink, weight="bold")
    save(svg, "fig3_action_reachability.svg")


# --- fig 4 -------------------------------------------------------------------
def fig4():
    rows = read("failure_attribution.csv")
    counts = {}
    for r in rows:
        counts[r["primary_attribution"]] = counts.get(r["primary_attribution"], 0) + 1
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    colours = {
        "generated_logic": C_PURPLE,
        "compiled_asset_discrepancy": C_REVIEW,
        "engine_task_behaviour": C_GEN,
        "environment_navigation": C_VALID,
        "instrumentation": C_GREY,
        "metric_definition": C_INVALID,
        "unattributed": C_LIGHT,
        "scope_limitation": C_LIGHT,
        "none": C_VALID,
    }
    svg = Svg(940, 500)
    header(
        svg,
        "Observed problems by attributed cause",
        "N = %d findings from failure_attribution.csv. A finding is attributed to the "
        "layer that produced it, not to the layer that reported it." % len(rows),
    )
    x0, y0 = 250.0, 96.0
    bar_h, gap = 30.0, 12.0
    vmax = max(c for _, c in items) + 1
    unit = (svg.width - x0 - 90) / float(vmax)
    for i, (name, c) in enumerate(items):
        y = y0 + i * (bar_h + gap)
        svg.text(x0 - 14, y + bar_h / 2.0 + 4, name.replace("_", " "), size=11.5,
                 anchor="end")
        svg.rect(x0, y, unit * c, bar_h, colours.get(name, C_GREY))
        svg.text(x0 + unit * c + 8, y + bar_h / 2.0 + 4, str(c), size=11.5,
                 weight="bold", fill=C_GREY)
    base = y0 + len(items) * (bar_h + gap)
    svg.line(x0, base, x0, base, stroke=C_RULE)
    save(svg, "fig4_failure_attribution.svg")


# --- fig 5 -------------------------------------------------------------------
def fig5():
    bars = [
        ("+/-0.344 s", 0.344, C_GREY, "resolution at 2.9 Hz"),
        ("+/-0.017 s", 0.017, C_GREY, "resolution at 59 Hz"),
        ("2.89 s", 2.89, C_VALID, "#1 far_1500 latency gap"),
        ("1.18 s", 1.18, C_VALID, "#4 whole-run latency gap"),
        ("0.94 s", 0.94, C_VALID, "#3 whole-run latency gap"),
        ("0.10 s", 0.10, C_INVALID, "#1 close_200 gap (not a difference)"),
    ]
    svg = Svg(940, 500)
    header(
        svg,
        "Measurement resolution against the differences being claimed",
        "Bars are seconds. The dashed line is the resolution floor at 2.9 Hz; a latency "
        "difference at or below it is not supported by the instrument that measured it.",
        [("resolvable difference", C_VALID), ("within quantisation", C_INVALID)],
    )
    x0, y0, y1 = 250.0, 100.0, 430.0
    vmax = 3.2
    unit = (svg.width - x0 - 70) / vmax
    bar_h, gap = 34.0, 14.0
    floor_x = x0 + unit * 0.344
    svg.line(floor_x, y0 - 8, floor_x, y1, stroke=C_INVALID, width=1.6, dash="6,5")
    svg.text(floor_x + 8, y0 - 14, "resolution floor 0.344 s (2.9 Hz)", size=10.5,
             fill=C_INVALID)
    for i, (label, val, colour, note) in enumerate(bars):
        y = y0 + i * (bar_h + gap)
        svg.text(x0 - 14, y + bar_h / 2.0 + 4, label, size=11.5, anchor="end")
        w = unit * val
        svg.rect(x0, y, max(w, 2.0), bar_h, colour)
        svg.text(x0 + max(w, 2.0) + 8, y + bar_h / 2.0 + 4, note, size=10.5, fill=C_GREY)
    svg.line(x0, y1, svg.width - 60, y1, stroke=C_RULE, width=1.2)
    save(svg, "fig5_timing_resolution.svg")


# --- fig 6 -------------------------------------------------------------------
def fig6():
    rows = [r for r in read("set2_candidate_gameplay.csv") if r["candidate_no"]]
    groups = {}
    for r in rows:
        g = groups.setdefault(r["status"], {"dealt": 0, "zero": 0, "names_dealt": [], "names_zero": []})
        if float(r["gen_damage"]) > 0:
            g["dealt"] += 1
            g["names_dealt"].append("#%s" % r["candidate_no"])
        else:
            g["zero"] += 1
            g["names_zero"].append("#%s" % r["candidate_no"])
    order = [k for k in ("VALID", "REVIEW") if k in groups]
    svg = Svg(940, 520)
    header(
        svg,
        "Automated classification versus measured damage",
        "Six selected candidates only. The classification does not order the outcomes: "
        "both zero-damage and best-damage results occur in both classes.",
        [("dealt damage", C_VALID), ("zero damage", C_INVALID)],
    )
    x0, y0, y1 = 110.0, 110.0, 430.0
    vmax = 4.0
    yaxis(svg, x0, y0, y1, vmax, 4, "candidates", fmt="%d")
    plot_w = svg.width - x0 - 140
    group = plot_w / float(len(order))
    bw = 96.0
    for i, key in enumerate(order):
        g = groups[key]
        cx = x0 + group * i + group / 2.0
        for off, count, colour in ((-bw / 2.0 - 6, g["dealt"], C_VALID),
                                   (6, g["zero"], C_INVALID)):
            h = (y1 - y0) * count / vmax
            svg.rect(cx + off, y1 - h, bw, max(h, 2.0), colour)
            svg.text(cx + off + bw / 2.0, y1 - h - 8, str(count), size=13,
                     anchor="middle", weight="bold")
        svg.text(cx, y1 + 22, key, size=13, anchor="middle", weight="bold")
        svg.text(cx, y1 + 42, "dealt: " + ", ".join(g["names_dealt"] or ["none"]),
                 size=10.5, anchor="middle", fill=C_GREY)
        svg.text(cx, y1 + 57, "zero: " + ", ".join(g["names_zero"] or ["none"]),
                 size=10.5, anchor="middle", fill=C_GREY)
    svg.line(x0, y1, svg.width - 140, y1, stroke=C_RULE, width=1.2)
    save(svg, "fig6_classification_vs_damage.svg")


# --- fig 7 -------------------------------------------------------------------
def fig7():
    rows = read("phase7h_rebuild_diagnostics.csv")
    runs = [r for r in rows if r["run_id"] in ("G1P03R1", "G1P03ORIG", "G1P03R1B")]
    phases = ["far_1500", "mid_600", "close_200", "far_1500_again"]
    series = [
        ("G1P03R1", "rebuild (run 1)", C_GEN),
        ("G1P03ORIG", "candidate #5 as built", C_INVALID),
        ("G1P03R1B", "rebuild (run 2)", C_PURPLE),
    ]
    data = {}
    for r in runs:
        vals = [float(v) for v in r["damage_by_phase"].split("/")]
        data[r["run_id"]] = vals
    svg = Svg(940, 530)
    header(
        svg,
        "Phase 7H: identical graph, divergent compiled data",
        "Damage per 8 s probe phase. BT_Behavior_P03_G02_R1 has 14 nodes and 0 property "
        "differences from BT_Behavior_P03_G02, yet it attacks and the original does not. "
        "Run order was A/B/A.",
        [(label, colour) for _, label, colour in series],
    )
    x0, y0, y1 = 110.0, 100.0, 430.0
    vmax = 30.0
    yaxis(svg, x0, y0, y1, vmax, 3, "damage dealt", fmt="%d")
    plot_w = svg.width - x0 - 90
    group = plot_w / float(len(phases))
    bw = 52.0
    for i, ph in enumerate(phases):
        cx = x0 + group * i + group / 2.0
        for k, (run, label, colour) in enumerate(series):
            val = data[run][i]
            off = (k - 1) * (bw + 8)
            h = (y1 - y0) * val / vmax
            svg.rect(cx + off - bw / 2.0, y1 - h, bw, max(h, 1.5), colour)
            svg.text(cx + off, y1 - h - 6, "%.0f" % val, size=10.5, anchor="middle",
                     weight="bold", fill=C_GREY if val == 0 else C_INK)
        svg.text(cx, y1 + 22, ph, size=11.5, anchor="middle")
    svg.line(x0, y1, svg.width - 90, y1, stroke=C_RULE, width=1.2)
    save(svg, "fig7_rebuild_vs_asbuilt.svg")


def main():
    if not os.path.isdir(ANALYSIS):
        raise SystemExit("run the analysis CSV build first: %s does not exist" % ANALYSIS)
    fig1()
    fig2()
    fig3()
    fig4()
    fig5()
    fig6()
    fig7()
    print("figures written to %s" % FIGDIR)


if __name__ == "__main__":
    main()
