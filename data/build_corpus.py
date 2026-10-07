#!/usr/bin/env python3
"""Build the SolarGuard Space retrieval corpus:
   - extract remaining PDF (JMRT) with page markers
   - write KAUST abstract docs from the reader markdown
   - write DustIQ product-page doc from saved HTML
   - chunk every corpus/*.txt into chunks.jsonl (BM25-friendly)
"""
import json, os, re, html
from html.parser import HTMLParser

BASE = "/home/hermes2/solarguard-space"
PAPERS = f"{BASE}/data/papers"
CORPUS = f"{BASE}/data/corpus"
os.makedirs(CORPUS, exist_ok=True)

import pymupdf as fitz

# ---------------------------------------------------------------- 1. JMRT PDF
jmrt = "jmrt-S2238785425027103-main.pdf"
d = fitz.open(os.path.join(PAPERS, jmrt))
parts = [f"\n<<<PAGE {i}>>>\n" + pg.get_text("text") for i, pg in enumerate(d, 1)]
txt = re.sub(r"[ \t]+", " ", "".join(parts)); txt = re.sub(r"\n{3,}", "\n\n", txt)
open(f"{CORPUS}/jmrt-s2238785425027103.txt", "w", encoding="utf-8").write(txt)
print(f"jmrt-s2238785425027103.txt pages={d.page_count} chars={len(txt)}")
d.close()

# ------------------------------------------------- 2. KAUST abstracts (reader)
KAUST = [
    ("kaust-665153-soiling-loss-rate-hot-humid-desert",
     "https://repository.kaust.edu.sa/handle/10754/665153", "_jina_665153.md"),
    ("kaust-696394-coarse-dust-soiling-fine-dust-dimming-arabian-peninsula",
     "https://repository.kaust.edu.sa/handle/10754/696394", "_jina_696394.md"),
]
for slug, url, md in KAUST:
    raw = open(os.path.join(BASE, "data", md), encoding="utf-8").read()
    raw = re.sub(r"\]\(https?://[^)]+\)", "]", raw)          # strip link targets
    raw = re.sub(r"\[Image \d+[^\]]*\]", " ", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
    out = f"Title: {raw.splitlines()[0].replace('Title: ','')}\nSource: {url}\n\n{raw}"
    open(f"{CORPUS}/{slug}.txt", "w", encoding="utf-8").write(out)
    print(f"{slug}.txt chars={len(out)}")

# ------------------------------------------------------------- 3. DustIQ page
class Stripper(HTMLParser):
    def __init__(self):
        super().__init__(); self.buf=[]; self.skip=0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"): self.skip += 1
    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self.skip: self.skip -= 1
    def handle_data(self, data):
        if not self.skip:
            s = data.strip()
            if s: self.buf.append(s)

p = Stripper()
p.feed(open(f"{BASE}/data/_dustiq.html", encoding="utf-8", errors="replace").read())
dt = "\n".join(p.buf)
dt = re.sub(r"\n{3,}", "\n\n", dt)
hdr = ("Title: DustIQ Soiling Monitoring System (Kipp & Zonen)\n"
       "Source: https://www.kippzonen.com/products/dustiq-soiling-monitoring-system\n\n")
open(f"{CORPUS}/dustiq-soiling-monitoring-system.txt", "w", encoding="utf-8").write(hdr + dt)
print(f"dustiq-soiling-monitoring-system.txt chars={len(dt)}")

# ----------------------------------------------------------------- 4. Chunker
PAGE_RE = re.compile(r"<<<PAGE (\d+)>>>")
DOCMETA = {
    "iea-pvps-t13-21-2022-soiling-losses-pv-plants":
        "https://iea-pvps.org/wp-content/uploads/2023/01/IEA-PVPS-T13-21-2022-REPORT-Soiling-Losses-PV-Plants.pdf",
    "energies-15-08033":
        "https://res.mdpi.com/d_attachment/energies/energies-15-08033/article_deploy/energies-15-08033.pdf",
    "energies-19-04373":
        "https://res.mdpi.com/d_attachment/energies/energies-19-04373/article_deploy/energies-19-04373.pdf",
    "jmrt-s2238785425027103":
        "https://www.sciencedirect.com/science/article/pii/S2238785425027103",
    "kaust-665153-soiling-loss-rate-hot-humid-desert":
        "https://repository.kaust.edu.sa/handle/10754/665153",
    "kaust-696394-coarse-dust-soiling-fine-dust-dimming-arabian-peninsula":
        "https://repository.kaust.edu.sa/handle/10754/696394",
    "dustiq-soiling-monitoring-system":
        "https://www.kippzonen.com/products/dustiq-soiling-monitoring-system",
}

CHUNK, OVERLAP = 1200, 150   # target window ~1000-1400 chars, 150 char overlap

def split_page(text):
    """Split a page of text into ~CHUNK-char windows at word boundaries."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text: return []
    if len(text) <= CHUNK + 200: return [text]
    out, start = [], 0
    while start < len(text):
        end = min(start + CHUNK, len(text))
        if end < len(text):
            cut = text.rfind(" ", start + CHUNK - 250, end)
            if cut > start: end = cut
        out.append(text[start:end].strip())
        if end >= len(text): break
        start = max(end - OVERLAP, start + 1)
    return out

chunks, cid = [], 0
for fn in sorted(os.listdir(CORPUS)):
    if not fn.endswith(".txt"): continue
    slug = fn[:-4]
    url = DOCMETA.get(slug, "")
    raw = open(os.path.join(CORPUS, fn), encoding="utf-8").read()
    # split into (page, text) blocks; docs without markers => page 1
    if "<<<PAGE " in raw:
        blocks, pos = [], 0
        for m in PAGE_RE.finditer(raw):
            if pos: blocks.append((cur_page, raw[pos:m.start()]))
            cur_page = int(m.group(1)); pos = m.end()
        blocks.append((cur_page, raw[pos:]))
    else:
        blocks = [(1, raw)]
    for page, body in blocks:
        for piece in split_page(body):
            if len(piece) < 60:   # drop fragments that carry no retrieval value
                continue
            cid += 1
            chunks.append({"id": f"chunk-{cid:05d}", "source": slug,
                           "url": url, "page": page, "text": piece})

with open(f"{CORPUS}/chunks.jsonl", "w", encoding="utf-8") as f:
    for c in chunks:
        f.write(json.dumps(c, ensure_ascii=False) + "\n")

lens = [len(c["text"]) for c in chunks]
print(f"\nchunks={len(chunks)}  bytes={os.path.getsize(CORPUS+'/chunks.jsonl')}")
print(f"chunk chars: min={min(lens)} max={max(lens)} avg={sum(lens)//len(lens)}")
from collections import Counter
for s, n in Counter(c["source"] for c in chunks).most_common():
    print(f"  {n:5d}  {s}")
