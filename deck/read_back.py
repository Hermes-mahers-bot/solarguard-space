"""Read the deck back: slide count, every text run, notes, and any empty shapes."""
import sys

from pptx import Presentation
from pptx.util import Emu

path = sys.argv[1] if len(sys.argv) > 1 else "deck/SolarGuard-Rubric.pptx"
prs = Presentation(path)
print(f"slides: {len(prs.slides)}   size: {prs.slide_width / 914400:.3f} x {prs.slide_height / 914400:.3f} in")

empty = 0
for i, s in enumerate(prs.slides, 1):
    texts = []
    off_slide = []
    for sh in s.shapes:
        if sh.has_text_frame:
            t = sh.text_frame.text.strip()
            if t:
                texts.append(t)
            elif sh.shape_type is not None and sh.width and sh.height:
                empty += 1
        # anything outside the canvas would be invisible in PowerPoint
        if sh.left is not None and (sh.left < 0 or sh.top < 0
                                    or sh.left + (sh.width or 0) > prs.slide_width
                                    or sh.top + (sh.height or 0) > prs.slide_height):
            off_slide.append(f"{sh.shape_type} at {Emu(sh.left).inches:.2f},{Emu(sh.top).inches:.2f}")
    head = texts[0][:52] if texts else "(no text)"
    notes = s.notes_slide.notes_text_frame.text.strip() if s.has_notes_slide else ""
    print(f"\n{i:>2}. {head}")
    for t in texts[1:5]:
        print(f"      · {t[:78]}")
    print(f"      runs={len(texts)} notes={'yes ' + str(len(notes)) + 'ch' if notes else 'NO'}"
          + (f"  OFF-SLIDE: {off_slide}" if off_slide else ""))
print(f"\nshapes with no text: {empty}")
