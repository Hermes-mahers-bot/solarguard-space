#!/usr/bin/env python3
"""Build the SolarGuard deck (16:9 pptx) + an HTML preview of the same slides.

Design from the team's scroll-story page: near-black ground, hairline cards, one warm
accent, mono labels. Judge-facing copy only — no scoring language anywhere on a slide
(the evidence still lines up with the brief; that lives in the speaker notes).

    python3 deck/build_deck.py     ->  deck/SolarGuard.pptx + deck/preview.html
"""
from __future__ import annotations

import html
import os

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

OUT = os.path.dirname(os.path.abspath(__file__))

SPACE = RGBColor(0x04, 0x06, 0x0C)
CARD = RGBColor(0x0B, 0x10, 0x1B)
CARD2 = RGBColor(0x14, 0x1B, 0x29)
LINE = RGBColor(0x23, 0x2C, 0x3C)
INK = RGBColor(0xF3, 0xF4, 0xF6)
MUTED = RGBColor(0x9A, 0xA3, 0xB2)
SUN = RGBColor(0xFF, 0x8A, 0x2B)
SUNINK = RGBColor(0xFF, 0xA4, 0x5C)
ORBIT = RGBColor(0x5B, 0x7C, 0xFF)
CLEAN = RGBColor(0x4A, 0xDE, 0x9B)
DARKINK = RGBColor(0x0E, 0x11, 0x17)

HEAD, BODY, MONO = "Arial", "Calibri", "Courier New"
W, H = 13.333, 7.5
PAL = {"space": "#04060c", "card": "#0b101b", "card2": "#141b29", "line": "#232c3c",
       "ink": "#f3f4f6", "muted": "#9aa3b2", "sun": "#ff8a2b", "sunink": "#ffa45c",
       "orbit": "#5b7cff", "clean": "#4ade9b", "darkink": "#0e1117"}

# ─────────────────────────────────────────────────────────────── content
SLIDES: list[dict] = [
    {"kind": "title",
     "eyebrow": "Dust intelligence for Saudi solar",
     "big": "SolarGuard",
     "sub": "You can't see the dust. We can.",
     "facts": ("12 OPEN FEEDS", "5 MODELS TRAINED", "1 VERDICT"),
     "foot": "Team space-Marines  ·  Riyadh and Dammam",
     "notes": "Open cold. One sentence: SolarGuard tells a Saudi solar plant, every "
              "morning, whether cleaning the panels today is worth the money."},

    {"kind": "cards3",
     "eyebrow": "What it is",
     "title": "Satellite in. One decision out.",
     "cards": [("Watch", "12 live open feeds: satellite dust, aerosol, wind, sun, rain.", "12 FEEDS"),
               ("Predict", "Our own AI models, trained in-house on 4 years of Saudi data.", "5 MODELS"),
               ("Decide", "CLEAN or WAIT, priced in riyals. Nothing installed on site.", "1 VERDICT")],
     "notes": "Three verbs only. The detail comes later."},

    {"kind": "pipeline",
     "eyebrow": "How it works",
     "title": "Five steps, satellite to decision",
     "steps": [("1", "Live data"), ("2", "AI models"), ("3", "Forecasts"),
               ("4", "Economics"), ("5", "CLEAN or WAIT")],
     "note": "The AI predicts. The physics engine decides.",
     "notes": "Stress step 5: the output is a decision, not a chart."},

    {"kind": "feature",
     "eyebrow": "Problem",
     "title": "Dust costs more than the cleaning it forces",
     "rows": [("Evidence", "Dust and sandstorms take 20-40% of output: 30-35% measured on the Saudi east coast, 20% from a single sandstorm.", "KAUST 2023 · Energies 2022"),
              ("Today", "Operators clean on a fixed calendar, or once a sensor says dust is already high. Neither asks what tomorrow brings.", "IEA-PVPS 2022"),
              ("Severity", "At a 100 MWp plant: 10.78M SAR a year cleaning weekly, 16.13M never cleaning at all.", "our simulation")],
     "notes": "Sources are on the slide. If challenged on 10.78/16.13, say it is our own "
              "simulation and give the assumptions: 100 MWp, Dammam, 1,800 SAR per MWp per pass."},

    {"kind": "feature",
     "eyebrow": "What's different",
     "title": "From a calendar to an economic forecast",
     "rows": [("Compared", "The closest approaches: a fixed calendar, and dust-threshold sensors that need hardware and react once the loss has started.", "closest available"),
              ("Ours", "We turn cleaning into a forecast plus economics: one riyal decision per site per day, with no hardware on site.", "our contribution"),
              ("Trade-off", "Output error 0.234 against 2.572 kWh/kWp for the naive guess, 11x better. At a site we have never seen, accuracy drops to AUC 0.785.", "tested, limitation stated")],
     "notes": "Naming the trade-off openly is deliberate. If asked about sensors, say they "
              "measure soiling we already predict from orbit, at a fraction of the cost."},

    {"kind": "feature",
     "eyebrow": "What it delivers",
     "title": "One verdict an operator can act on",
     "rows": [("The target", "Beat the 10-day habit on annual cost, at equal or better energy: 6.71M against 8.41M SAR a year, with 18 cleans.", "measurable target"),
              ("Safeguards", "A dead feed degrades a single number. If the AI is unavailable the physics engine answers. A bad request returns a clear error.", "by design"),
              ("Boundary", "Built for dust-dominated, low-rain desert sites. Snow, hydro and coastal fog are out of scope.", "stated, not implied")],
     "notes": "The success criterion is on the slide. Both agents of failure are handled in "
              "code and covered by tests."},

    {"kind": "feature",
     "eyebrow": "Can it be built",
     "title": "A 90-day pilot, software only",
     "rows": [("Assumption", "The core number, soiling at 0.2-0.8% per day in Saudi Arabia, comes from published measurement rather than guesswork.", "IEA-PVPS 2022 · KAUST 2020"),
              ("Plan", "Pilot at one 100 MWp plant in about 90 days. Estimate: one engineer plus cloud, roughly 15k SAR a month.", "estimate, assumptions stated"),
              ("Risks", "Two that matter: no inverter ground truth, and feed outages. Fixes: score against the plant's own inverters, and cache with a physics fallback.", "each with a fix")],
     "notes": "Say plainly that 15k SAR is our estimate, not a quote, and that cost is dominated "
              "by people rather than infrastructure."},

    {"kind": "feature",
     "eyebrow": "What we tested",
     "title": "Working, and measured against baselines",
     "rows": [("End to end", "Live: pick a site on the map, read the AI prediction, the verdict, and an agent answer with the tools it used.", "live, not mocked"),
              ("Baselines", "On 2,244 days it had never seen: storm AUC 0.952, output within 7.7%, soiling within 8.4%.", "measured"),
              ("Failure", "We hid a whole site and scored it (AUC 0.785), and we test that the data served can never drift from the data trained on.", "reliability reported")],
     "notes": "If judges want the failure test, the hidden-site block is in models/ai/metrics.json."},

    {"kind": "feature",
     "eyebrow": "Why Saudi Arabia",
     "title": "Built here, for here",
     "rows": [("Local", "Trained on 12 Saudi sites, from NEOM to Dammam, on Saudi dust measurements.", "local evidence"),
              ("Benefit", "Per 100 MWp site: about 1.7M SAR and 4.5M litres of water saved a year against the 10-day habit.", "simulated, assumptions stated"),
              ("Adoption", "The plant's operations manager opens the dashboard each morning, reads CLEAN or WAIT, and sends crews only when it pays.", "fits the workflow")],
     "notes": "The water figure matters because every pass skipped is water not used in a desert."},

    {"kind": "cards3",
     "eyebrow": "What is real",
     "title": "Built, estimated, and next",
     "cards": [("Built and tested", "Live on 12 open feeds. AI scored on 2,244 unseen days and on a hidden site. The agent cites its sources.", "WORKING"),
               ("Estimated", "Output comes from measured weather and physics, not inverter meters. Savings come from a one-year simulation.", "MODELLED"),
               ("Next", "Pilot at a real Saudi plant, compared against real inverter output, with site sensors and real costs.", "NEXT")],
     "notes": "This slide exists to draw the line between what we built and what we estimate. "
              "Volunteer it before anyone asks."},

    {"kind": "pipeline",
     "eyebrow": "Extra · how we trained the AI",
     "title": "Four years of Saudi dust, then five steps",
     "steps": [("1", "Collect"), ("2", "Build 37 inputs"), ("3", "Define targets"), ("4", "Split honestly"), ("5", "Train and blend")],
     "note": "18,348 site-days · 12 sites · 37 inputs · 1,540 trees · 22,725 weights",
     "rows": ["Every input is measured: satellite dust, aerosol, wind, sun and rain, plus how long since it rained.",
              "Every target is defined in code and documented: a measured storm threshold, and two physics formulas fed with measured weather.",
              "Two model families trained for each target and blended by measured skill. No GPU, no ML library: written in numpy, 16 minutes on CPU."],
     "notes": "The honest sentence here: no inverter data is public for Saudi plants, so two of "
              "the three targets are documented formulas rather than meter readings."},

    {"kind": "stats",
     "eyebrow": "Extra · what the models predict",
     "title": "Five models, and how wrong they are",
     "stats": [("0.952", "storm AUC, day +1"), ("7.7%", "output error"), ("8.4%", "soiling error")],
     "rows": ["Storm risk at +1, +2 and +3 days, so a crew can be booked before the dust lands.",
              "Tomorrow's output in kWh and kWh per kWp, which is the number that turns dust into riyals.",
              "Tomorrow's soiling loss, which drives the clean-or-wait verdict and the water saving."],
     "notes": "Leave-one-site-out: storm AUC 0.785 on a site the models never saw. Say that "
              "before being asked."},

    {"kind": "steps",
     "eyebrow": "Extra · the agentic AI",
     "title": "It asks, waits, then answers",
     "steps": [("1", "Operator asks"), ("2", "Model calls tools"), ("3", "Server runs them"), ("4", "Answer with sources")],
     "rows": ["10 tools over the live data, and retrieval over 672 indexed chunks of soiling research so answers carry citations.",
              "The model never speaks from memory: it asks for data, waits for the real output, then writes the answer.",
              "It acts on the page as well: it moves the map to a site and switches the satellite layer."],
     "notes": "Live answer to quote: 'WAIT, about 12,030 SAR lost this week against 180,000 SAR "
              "for one pass, so cleaning now costs roughly 15 times what it recovers.'"},

    {"kind": "close",
     "big": "CLEAN or WAIT",
     "sub": "From a fixed schedule to a data-driven economic decision.",
     "foot": "github.com/Hermes-mahers-bot/solarguard-space",
     "notes": "Stop talking. Let it land, then take questions."},
]


# ─────────────────────────────────────────────────────────────── pptx
def slide_base(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = SPACE
    return s


def put(s, x, y, w, h, text, *, size=15, color=INK, bold=False, font=BODY,
        align=PP_ALIGN.LEFT, line_spacing=1.15, anchor=MSO_ANCHOR.TOP):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    p.line_spacing = line_spacing
    r = p.add_run()
    r.text = text
    r.font.size, r.font.bold, r.font.name = Pt(size), bold, font
    r.font.color.rgb = color
    return tb


def card(s, x, y, w, h, *, fill=CARD, line=LINE, radius=0.055):
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.adjustments[0] = radius
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(0.75)
    sh.shadow.inherit = False
    return sh


def chip(s, x, y, w, h, text, *, fill=CARD2, color=INK, size=11, font=MONO, bold=True):
    sh = card(s, x, y, w, h, fill=fill, line=None, radius=0.28)
    tf = sh.text_frame
    tf.word_wrap = False
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = text
    r.font.size, r.font.bold, r.font.name = Pt(size), bold, font
    r.font.color.rgb = color
    return sh


def eyebrow(s, text, y=0.62):
    put(s, 0.9, y, 9.0, 0.3, text.upper(), size=11, color=SUNINK, bold=True, font=MONO)


def title(s, text, y=1.0, size=34, w=11.5):
    put(s, 0.9, y, w, 0.9, text, size=size, color=INK, bold=True, font=HEAD, line_spacing=1.02)


def cols(n, gap=0.22, left=0.9, right=0.9):
    """Card width and pitch for n columns inside the margins, so a row can never run
    off the slide edge."""
    total = W - left - right
    w = (total - (n - 1) * gap) / n
    return w, w + gap


def build_pptx(path):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)

    for sl in SLIDES:
        k = sl["kind"]
        s = slide_base(prs)
        s.notes_slide.notes_text_frame.text = sl.get("notes", "")

        if k == "title":
            put(s, 0.9, 2.05, 10.0, 0.4, sl["eyebrow"].upper(), size=12, color=SUNINK, bold=True, font=MONO)
            put(s, 0.87, 2.5, 12.0, 1.7, sl["big"], size=88, color=INK, bold=True, font=HEAD, line_spacing=0.9)
            put(s, 0.9, 4.35, 10.0, 0.5, sl["sub"], size=22, color=MUTED)
            for j, fact in enumerate(sl["facts"]):
                chip(s, 0.9 + j * 2.75, 5.35, 2.45, 0.52, fact, fill=CARD, color=MUTED)
            put(s, 0.9, 6.55, 10.0, 0.35, sl["foot"], size=12, color=MUTED, font=MONO)

        elif k == "cards3":
            eyebrow(s, sl["eyebrow"])
            title(s, sl["title"])
            cw, step = cols(3, gap=0.39)
            for j, (h, body, metric) in enumerate(sl["cards"]):
                x = 0.9 + j * step
                tall = 2.55 if metric else 2.75
                card(s, x, 2.45, cw, tall)
                put(s, x + 0.34, 2.78, cw - 0.68, 0.4, h, size=24, color=SUNINK, bold=True, font=HEAD)
                put(s, x + 0.34, 3.42, cw - 0.68, 1.0, body, size=14.5, color=MUTED, line_spacing=1.3)
                if metric:
                    chip(s, x + 0.34, 4.42, 1.6, 0.4, metric, fill=CARD2, color=MUTED)

        elif k == "pipeline":
            eyebrow(s, sl["eyebrow"])
            title(s, sl["title"])
            cw, step = cols(len(sl["steps"]))
            for j, (n, lab) in enumerate(sl["steps"]):
                x = 0.9 + j * step
                card(s, x, 2.5, cw, 1.75)
                chip(s, x + 0.28, 2.78, 0.5, 0.5, n, fill=SUN, color=DARKINK, size=16, font=HEAD)
                put(s, x + 0.28, 3.45, cw - 0.56, 0.7, lab, size=14.5, color=INK, bold=True, line_spacing=1.12)
            put(s, 0.9, 4.55, 11.4, 0.45, sl["note"], size=17, color=SUNINK, bold=True, font=HEAD)
            if sl.get("rows"):
                y = 5.15
                for line in sl["rows"]:
                    card(s, 0.9, y, 11.53, 0.62)
                    put(s, 1.2, y + 0.17, 11.0, 0.35, line, size=12.5, color=MUTED)
                    y += 0.71

        elif k == "feature":
            eyebrow(s, sl["eyebrow"])
            title(s, sl["title"])
            y = 2.25
            for lead, text, src in sl["rows"]:
                card(s, 0.9, y, 11.53, 1.16)
                put(s, 1.2, y + 0.2, 1.5, 0.8, lead, size=14, color=SUNINK, bold=True,
                    anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.1)
                put(s, 2.85, y + 0.2, 7.7, 0.8, text, size=14.5, color=INK,
                    line_spacing=1.22, anchor=MSO_ANCHOR.MIDDLE)
                put(s, 10.75, y + 0.26, 1.5, 0.64, src, size=9.5, color=MUTED, font=MONO,
                    align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
                y += 1.33

        elif k == "stats":
            eyebrow(s, sl["eyebrow"])
            title(s, sl["title"])
            cw, step = cols(3, gap=0.35)
            for j, (big, lab) in enumerate(sl["stats"]):
                x = 0.9 + j * step
                card(s, x, 2.35, cw, 1.85)
                put(s, x + 0.35, 2.58, cw - 0.7, 0.95, big, size=52, color=SUNINK, bold=True, font=HEAD)
                put(s, x + 0.35, 3.56, cw - 0.7, 0.4, lab, size=13, color=MUTED)
            y = 4.5
            for line in sl["rows"]:
                put(s, 0.9, y, 11.4, 0.5, "·  " + line, size=14, color=MUTED, line_spacing=1.2)
                y += 0.56

        elif k == "steps":
            eyebrow(s, sl["eyebrow"])
            title(s, sl["title"])
            cw, step = cols(len(sl["steps"]))
            for j, (n, lab) in enumerate(sl["steps"]):
                x = 0.9 + j * step
                card(s, x, 2.3, cw, 1.65)
                chip(s, x + 0.28, 2.56, 0.48, 0.44, n, fill=SUN, color=DARKINK, size=14, font=HEAD)
                put(s, x + 0.28, 3.14, cw - 0.56, 0.65, lab, size=14.5, color=INK, bold=True,
                    line_spacing=1.12)
            y = 4.25
            for line in sl["rows"]:
                card(s, 0.9, y, 11.53, 0.68)
                put(s, 1.2, y + 0.2, 11.0, 0.35, line, size=13, color=MUTED)
                y += 0.79

        elif k == "close":
            put(s, 0.9, 2.3, 11.5, 1.4, sl["big"], size=76, color=INK, bold=True, font=HEAD,
                line_spacing=0.95)
            put(s, 0.9, 3.95, 10.5, 0.6, sl["sub"], size=20, color=MUTED)
            put(s, 0.9, 6.5, 10.0, 0.35, sl["foot"], size=12, color=MUTED, font=MONO)

    prs.save(path)
    return len(SLIDES)


# ─────────────────────────────────────────────────────────────── html
def build_html(path):
    def rect(x, y, w, h, bg, *, border=None, r=6):
        b = f"border:1px solid {border};" if border else ""
        return (f'<div style="position:absolute;left:{x*96:.0f}px;top:{y*96:.0f}px;'
                f'width:{w*96:.0f}px;height:{h*96:.0f}px;background:{bg};{b}'
                f'border-radius:{r}px"></div>')

    def txt(x, y, w, h, t, size, color, *, bold=False, mono=False, align="left", ls=1.2,
            middle=False):
        fam = ("Courier New, monospace" if mono else
               ("Arial, Helvetica, sans-serif" if bold else "Calibri, Carlito, Arial, sans-serif"))
        extra = "display:flex;align-items:center;" if middle else ""
        return (f'<div style="position:absolute;left:{x*96:.0f}px;top:{y*96:.0f}px;'
                f'width:{w*96:.0f}px;height:{h*96:.0f}px;{extra}color:{color};'
                f'font:{("700 " if bold else "")}{size*1.333:.0f}px/1.2 {fam};'
                f'text-align:{align};line-height:{ls};white-space:pre-wrap">'
                f'<span style="width:100%">{html.escape(t)}</span></div>')

    out = ['<html><head><meta charset="utf-8"><style>',
           'body{margin:0;background:#111;font-family:Arial,sans-serif}',
           '.slide{position:relative;width:1280px;height:720px;background:%s;margin:0 0 18px 0;'
           'overflow:hidden}' % PAL["space"],
           '</style></head><body>']
    for i, sl in enumerate(SLIDES):
        k, s = sl["kind"], [f'<div class="slide" id="s{i}">']
        if k == "title":
            s.append(txt(0.9, 2.05, 10, 0.4, sl["eyebrow"].upper(), 12, PAL["sunink"], bold=True, mono=True))
            s.append(txt(0.87, 2.5, 12, 1.7, sl["big"], 88, PAL["ink"], bold=True, ls=0.9))
            s.append(txt(0.9, 4.35, 10, 0.5, sl["sub"], 22, PAL["muted"]))
            for j, fact in enumerate(sl["facts"]):
                s.append(rect(0.9 + j * 2.75, 5.35, 2.45, 0.52, PAL["card"], border=PAL["line"], r=8))
                s.append(txt(0.9 + j * 2.75, 5.35, 2.45, 0.52, fact, 11, PAL["muted"], mono=True,
                             align="center", middle=True))
            s.append(txt(0.9, 6.55, 10, 0.35, sl["foot"], 12, PAL["muted"], mono=True))
        elif k in ("cards3",):
            s.append(txt(0.9, 0.62, 9, 0.3, sl["eyebrow"].upper(), 11, PAL["sunink"], bold=True, mono=True))
            s.append(txt(0.9, 1.0, 11.5, 0.9, sl["title"], 34, PAL["ink"], bold=True, ls=1.02))
            cw, step = cols(3, gap=0.39)
            for j, (h, body, metric) in enumerate(sl["cards"]):
                x = 0.9 + j * step
                tall = 2.55 if metric else 2.75
                s.append(rect(x, 2.45, cw, tall, PAL["card"], border=PAL["line"], r=14))
                s.append(txt(x + 0.34, 2.78, cw - 0.68, 0.4, h, 24, PAL["sunink"], bold=True))
                s.append(txt(x + 0.34, 3.42, cw - 0.68, 1.0, body, 14.5, PAL["muted"], ls=1.3))
                if metric:
                    s.append(rect(x + 0.34, 4.42, 1.6, 0.4, PAL["card2"], r=8))
                    s.append(txt(x + 0.34, 4.42, 1.6, 0.4, metric, 10, PAL["muted"], mono=True,
                                 align="center", middle=True))
        elif k == "pipeline":
            s.append(txt(0.9, 0.62, 9, 0.3, sl["eyebrow"].upper(), 11, PAL["sunink"], bold=True, mono=True))
            s.append(txt(0.9, 1.0, 11.5, 0.9, sl["title"], 34, PAL["ink"], bold=True, ls=1.02))
            cw, step = cols(len(sl["steps"]))
            for j, (n, lab) in enumerate(sl["steps"]):
                x = 0.9 + j * step
                s.append(rect(x, 2.5, cw, 1.75, PAL["card"], border=PAL["line"], r=14))
                s.append(rect(x + 0.28, 2.78, 0.5, 0.5, PAL["sun"], r=10))
                s.append(txt(x + 0.28, 2.78, 0.5, 0.5, n, 16, PAL["darkink"], bold=True,
                             align="center", middle=True))
                s.append(txt(x + 0.28, 3.45, cw - 0.56, 0.7, lab, 14.5, PAL["ink"], bold=True))
            s.append(txt(0.9, 4.55, 11.4, 0.45, sl["note"], 17, PAL["sunink"], bold=True))
            if sl.get("rows"):
                y = 5.15
                for line in sl["rows"]:
                    s.append(rect(0.9, y, 11.53, 0.62, PAL["card"], border=PAL["line"], r=14))
                    s.append(txt(1.2, y + 0.17, 11.0, 0.35, line, 12.5, PAL["muted"]))
                    y += 0.71
        elif k == "feature":
            s.append(txt(0.9, 0.62, 9, 0.3, sl["eyebrow"].upper(), 11, PAL["sunink"], bold=True, mono=True))
            s.append(txt(0.9, 1.0, 11.5, 0.9, sl["title"], 34, PAL["ink"], bold=True, ls=1.02))
            y = 2.25
            for lead, text, src in sl["rows"]:
                s.append(rect(0.9, y, 11.53, 1.16, PAL["card"], border=PAL["line"], r=14))
                s.append(txt(1.2, y + 0.2, 1.5, 0.8, lead, 14, PAL["sunink"], bold=True, ls=1.1, middle=True))
                s.append(txt(2.85, y + 0.2, 7.7, 0.8, text, 14.5, PAL["ink"], ls=1.22, middle=True))
                s.append(txt(10.75, y + 0.26, 1.5, 0.64, src, 9.5, PAL["muted"], mono=True,
                             align="right", middle=True))
                y += 1.33
        elif k == "stats":
            s.append(txt(0.9, 0.62, 9, 0.3, sl["eyebrow"].upper(), 11, PAL["sunink"], bold=True, mono=True))
            s.append(txt(0.9, 1.0, 11.5, 0.9, sl["title"], 34, PAL["ink"], bold=True, ls=1.02))
            cw, step = cols(3, gap=0.35)
            for j, (big, lab) in enumerate(sl["stats"]):
                x = 0.9 + j * step
                s.append(rect(x, 2.35, cw, 1.85, PAL["card"], border=PAL["line"], r=14))
                s.append(txt(x + 0.35, 2.58, cw - 0.7, 0.95, big, 52, PAL["sunink"], bold=True))
                s.append(txt(x + 0.35, 3.56, cw - 0.7, 0.4, lab, 13, PAL["muted"]))
            y = 4.5
            for line in sl["rows"]:
                s.append(txt(0.9, y, 11.4, 0.5, "·  " + line, 14, PAL["muted"], ls=1.2))
                y += 0.56
        elif k == "steps":
            s.append(txt(0.9, 0.62, 9, 0.3, sl["eyebrow"].upper(), 11, PAL["sunink"], bold=True, mono=True))
            s.append(txt(0.9, 1.0, 11.5, 0.9, sl["title"], 34, PAL["ink"], bold=True, ls=1.02))
            cw, step = cols(len(sl["steps"]))
            for j, (n, lab) in enumerate(sl["steps"]):
                x = 0.9 + j * step
                s.append(rect(x, 2.3, cw, 1.65, PAL["card"], border=PAL["line"], r=14))
                s.append(rect(x + 0.28, 2.56, 0.48, 0.44, PAL["sun"], r=10))
                s.append(txt(x + 0.28, 2.56, 0.48, 0.44, n, 14, PAL["darkink"], bold=True,
                             align="center", middle=True))
                s.append(txt(x + 0.28, 3.14, cw - 0.56, 0.65, lab, 14.5, PAL["ink"], bold=True))
            y = 4.25
            for line in sl["rows"]:
                s.append(rect(0.9, y, 11.53, 0.68, PAL["card"], border=PAL["line"], r=14))
                s.append(txt(1.2, y + 0.2, 11.0, 0.35, line, 13, PAL["muted"]))
                y += 0.79
        elif k == "close":
            s.append(txt(0.9, 2.3, 11.5, 1.4, sl["big"], 76, PAL["ink"], bold=True, ls=0.95))
            s.append(txt(0.9, 3.95, 10.5, 0.6, sl["sub"], 20, PAL["muted"]))
            s.append(txt(0.9, 6.5, 10, 0.35, sl["foot"], 12, PAL["muted"], mono=True))
        s.append("</div>")
        out.append("".join(s))
    out.append("</body></html>")
    with open(path, "w") as fh:
        fh.write("\n".join(out))
    return len(SLIDES)


if __name__ == "__main__":
    n = build_pptx(os.path.join(OUT, "SolarGuard.pptx"))
    build_html(os.path.join(OUT, "preview.html"))
    old = os.path.join(OUT, "SolarGuard-Rubric.pptx")
    if os.path.exists(old):
        os.remove(old)                      # the rubric-named file is retired
    print(f"slides: {n}")
    print("wrote", os.path.join(OUT, "SolarGuard.pptx"))
    print("wrote", os.path.join(OUT, "preview.html"))
