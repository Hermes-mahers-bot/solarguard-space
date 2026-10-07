#!/usr/bin/env python3
"""Extract PDFs -> plain text with page markers. Uses pymupdf (fitz)."""
import json, os, re, sys
try:
    import pymupdf as fitz
    EXTRACTOR = "pymupdf 1.26 (fitz)"
except ImportError:
    try:
        import fitz
        EXTRACTOR = "pymupdf (fitz legacy import)"
    except ImportError:
        print("NO PYMUPDF"); sys.exit(2)

BASE = "/home/hermes2/solarguard-space"
PAPERS = f"{BASE}/data/papers"
CORPUS = f"{BASE}/data/corpus"
os.makedirs(CORPUS, exist_ok=True)

DOCS = [
    ("IEA-PVPS-T13-21-2022-Soiling-Losses-PV-Plants.pdf",
     "iea-pvps-t13-21-2022-soiling-losses-pv-plants",
     "https://iea-pvps.org/wp-content/uploads/2023/01/IEA-PVPS-T13-21-2022-REPORT-Soiling-Losses-PV-Plants.pdf"),
    ("energies-15-08033.pdf", "energies-15-08033",
     "https://res.mdpi.com/d_attachment/energies/energies-15-08033/article_deploy/energies-15-08033.pdf"),
    ("energies-19-04373.pdf", "energies-19-04373",
     "https://res.mdpi.com/d_attachment/energies/energies-19-04373/article_deploy/energies-19-04373.pdf"),
]

manifest = []
for fname, slug, url in DOCS:
    path = os.path.join(PAPERS, fname)
    doc = fitz.open(path)
    parts = []
    for i, page in enumerate(doc, start=1):
        # page marker on its own line so the chunker can recover page numbers
        parts.append(f"\n<<<PAGE {i}>>>\n" + page.get_text("text"))
    txt = "".join(parts)
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    out = os.path.join(CORPUS, slug + ".txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(txt)
    manifest.append({
        "slug": slug, "source_file": fname, "url": url,
        "pages": doc.page_count, "chars": len(txt),
        "extractor": EXTRACTOR, "bytes": os.path.getsize(out),
        "pdf_bytes": os.path.getsize(path),
    })
    print(f"{slug:45s} pages={doc.page_count:4d} chars={len(txt):8d} bytes={os.path.getsize(out):8d}")
    doc.close()

with open(f"{BASE}/data/_extract_manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)
print("EXTRACTOR:", EXTRACTOR)
