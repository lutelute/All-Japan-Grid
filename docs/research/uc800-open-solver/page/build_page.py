import base64, json, sys
from pathlib import Path
S = Path(__file__).resolve().parent                     # the page kit: compact data next to this file
R = S.parent / "results"
s = (S.parent / "story_page.template.html").read_text()
fr = json.loads((R / "gpu3060/frontier-20261025/frontier.json").read_text())
for c in fr["cells"]:
    c["trace"] = [[t, round(g, 5)] for t, g in c["trace"]]
video = "--no-video" not in sys.argv and (S / "uc800-story-v3_480p.mp4").exists()
video_files = "--video-files" in sys.argv          # reference the videos as files next to the page (smaller upload) instead of inlining them
v1 = "uc800-story-v3_480p.mp4" if video_files else "data:video/mp4;base64," + base64.b64encode((S / "uc800-story-v3_480p.mp4").read_bytes()).decode() if video else ""
v2 = "uc-principles-v4_480p.mp4" if video_files else "data:video/mp4;base64," + base64.b64encode((S / "uc-principles-v4_480p.mp4").read_bytes()).decode() if video else ""
parts = {"__BNB_DATA__": (S / "bnb_compact.json").read_text(), "__FRONTIER_DATA__": json.dumps(fr, separators=(",", ":")),
         "__PROFILE_DATA__": (S / "profile_compact.json").read_text(), "__GEO_DATA__": (S / "geo_compact.json").read_text(),
         "__YEAR_DATA__": (S / "year_compact.json").read_text() if (S / "year_compact.json").exists() else "null", "__STAGE2_DATA__": (S / "stage2_compact.json").read_text() if (S / "stage2_compact.json").exists() else "null", "__SOLVER_DATA__": (S / "solver_compact.json").read_text(), "__CGMAP_DATA__": (S / "cgmap_compact.json").read_text() if (S / "cgmap_compact.json").exists() else "null", "__NET_DATA__": (S / "net_compact.json").read_text(), "__ZC_DATA__": (S / "zc_compact.json").read_text(), "__NEAR_DATA__": (S / "near_compact.json").read_text(), "__ABL_DATA__": (S / "ablation_compact.json").read_text(), "__STAGED_DATA__": (S / "staged_compact.json").read_text() if (S / "staged_compact.json").exists() else "null",
         "__VIDEO_DATA__": v1, "__VIDEO2_DATA__": v2}
for k, v in parts.items():
    s = s.replace(k, v)
OUT = S / "build"; OUT.mkdir(exist_ok=True)
out = OUT / "uc800-story.html"
if video:
    out.write_text(s)
(OUT / "check.html").write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + s)
print("ok", len(s))
