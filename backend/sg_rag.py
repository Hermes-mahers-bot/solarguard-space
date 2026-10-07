"""
SolarGuard Space — retrieval layer for the AI assistant.

A hand-written BM25 retriever (Okapi, k1=1.5, b=0.75) over:
  * data/corpus/chunks.jsonl  — the harvested literature (IEA-PVPS soiling
    report, MDPI Energies papers, KAUST repository items, product docs)
  * data/knowledge.json       — curated cited facts
  * docs/FACTS_SHEET.md, docs/DATA_SOURCES.md, README.md

Why BM25 and not embeddings: DeepSeek's public API has no embeddings endpoint and
this box has no local embedding model, so a lexical retriever is the honest
choice. It is also *better* here than a fuzzy vector search: the queries are full
of exact tokens that must match (PM10, MAIAC, soiling, soiling-loss percentages,
"Sudair", "SAR"), and BM25 nails those. No external service, no key, ~5 ms.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from sg_config import CORPUS, DOCS, ROOT

STOP = set("""a an the and or but if then than that this these those of in on at to for from with without by as is are was were be been being it its into over under about after before during between within not no nor so such only own same too very can will just should now also per via we our you your they their he she his her i me my more most some any each other another".split()""".split())

_token_re = re.compile(r"[a-z0-9][a-z0-9\.\-_%]*")


def tokenize(text: str) -> list[str]:
    return [t for t in _token_re.findall(text.lower()) if t not in STOP and len(t) > 1]


class BM25:
    def __init__(self, docs: list[dict], k1: float = 1.5, b: float = 0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.tokens = [tokenize(d["text"]) for d in docs]
        self.tf = [Counter(t) for t in self.tokens]
        self.len = [len(t) for t in self.tokens]
        self.avg_len = (sum(self.len) / len(self.len)) if self.len else 1.0
        df = Counter()
        for t in self.tokens:
            for w in set(t):
                df[w] += 1
        n = max(len(docs), 1)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def search(self, query: str, k: int = 6) -> list[dict]:
        q = tokenize(query)
        if not q:
            return []
        scores = [0.0] * len(self.docs)
        for w in set(q):
            if w not in self.idf:
                continue
            q_weight = 1.0 + 0.5 * (q.count(w) / len(q))
            idf = self.idf[w]
            for i, tf in enumerate(self.tf):
                f = tf.get(w, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg_len)
                scores[i] += q_weight * idf * (f * (self.k1 + 1)) / denom
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        out = []
        for i in order[:k]:
            if scores[i] <= 0:
                continue
            d = dict(self.docs[i])
            d["score"] = round(scores[i], 3)
            out.append(d)
        return out


# ------------------------------------------------------------------ loading
def _chunk_markdown(text: str, source: str, url: str = "", size: int = 1200, overlap: int = 150):
    text = text.strip()
    out, i = [], 0
    while i < len(text):
        piece = text[i:i + size]
        if piece.strip():
            out.append({"source": source, "url": url, "page": None, "text": piece.strip()})
        i += size - overlap
    return out


def load_corpus() -> list[dict]:
    docs: list[dict] = []
    cj = CORPUS / "chunks.jsonl"
    if cj.exists():
        try:
            for line in cj.read_text(errors="ignore").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = (o.get("text") or "").strip()
                if len(t) > 80:
                    docs.append({"source": o.get("source", "corpus"),
                                 "url": o.get("url", ""), "page": o.get("page"),
                                 "text": t, "kind": "literature"})
        except Exception as e:
            print(f"[solarguard] corpus read failed: {e}")
    # knowledge facts as retrievable snippets
    kj = ROOT / "data" / "knowledge.json"
    if kj.exists():
        try:
            k = json.loads(kj.read_text())
            facts = k.get("facts", k if isinstance(k, list) else [])
            for f in facts if isinstance(facts, list) else []:
                txt = f.get("statement") or f.get("fact") or f.get("text") or ""
                if txt:
                    docs.append({"source": f.get("source", "knowledge base"),
                                 "url": f.get("url", ""), "page": None,
                                 "text": txt, "kind": "fact"})
        except Exception as e:
            print(f"[solarguard] knowledge.json read failed: {e}")
    for name, label in (("FACTS_SHEET.md", "FACTS_SHEET"),
                        ("DATA_SOURCES.md", "DATA_SOURCES"),
                        ("MODEL_CARD.md", "MODEL_CARD")):
        p = DOCS / name
        if p.exists():
            docs += _chunk_markdown(p.read_text(errors="ignore"), label, "")
    rd = ROOT / "README.md"
    if rd.exists():
        docs += _chunk_markdown(rd.read_text(errors="ignore"), "project README", "")
    return docs


_INDEX = None
_INDEX_STAMP = None


def index() -> BM25:
    """Lazily build the index; rebuild when the corpus files change."""
    global _INDEX, _INDEX_STAMP
    stamp = tuple(sorted(
        [(p.name, p.stat().st_mtime) for p in CORPUS.glob("*") if p.is_file()]
        + [(p.name, p.stat().st_mtime) for p in DOCS.glob("*.md")]
        + [("__readme__", (ROOT / "README.md").stat().st_mtime if (ROOT / "README.md").exists() else 0.0)]
    ))
    if _INDEX is None or stamp != _INDEX_STAMP:
        docs = load_corpus()
        _INDEX = BM25(docs) if docs else BM25([{"source": "empty", "text": "no corpus loaded", "url": ""}])
        _INDEX_STAMP = stamp
        print(f"[solarguard] RAG index built: {len(docs)} chunks, {len(_INDEX.idf)} terms")
    return _INDEX


def search(query: str, k: int = 6) -> list[dict]:
    return index().search(query, k)


def stats() -> dict:
    idx = index()
    srcs = Counter(d.get("source", "?") for d in idx.docs)
    return {"chunks": len(idx.docs), "vocabulary_terms": len(idx.idf),
            "retriever": "BM25 Okapi (k1=1.5, b=0.75), pure-Python",
            "sources": dict(srcs.most_common(20)),
            "corpus_files": sorted(p.name for p in CORPUS.glob("*") if p.is_file())}


def context_block(query: str, k: int = 6, max_chars: int = 4500) -> tuple[str, list[dict]]:
    """Retrieved evidence, formatted for the LLM prompt, with citations."""
    hits = search(query, k)
    used, cites, total = [], [], 0
    for h in hits:
        txt = h["text"]
        if total + len(txt) > max_chars:
            txt = txt[: max(0, max_chars - total)]
        if not txt:
            break
        total += len(txt)
        tag = f"[{len(cites)+1}]"
        used.append(f"{tag} {h['source']}"
                    + (f" (p.{h['page']})" if h.get("page") else "")
                    + f":\n{txt}")
        cites.append({"n": len(cites) + 1, "source": h["source"], "url": h.get("url", ""),
                      "page": h.get("page"), "score": h["score"]})
    return "\n\n".join(used), cites
