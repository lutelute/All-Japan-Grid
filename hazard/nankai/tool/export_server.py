#!/usr/bin/env python3
"""シナリオ卓の夜景をスライド用の動画にする受け皿: ツールの HTML を配りつつ、ブラウザが POST するフレーム PNG を保存する。

    python3 hazard/nankai/tool/export_server.py <html のあるフォルダ> <フレームの保存先> [port]
    → ブラウザで http://127.0.0.1:<port>/nankai_scenario_tool.html を開き、コンソールで window.exportNight() を呼ぶ
    → ffmpeg -framerate 20 -pattern_type glob -i 'frames/*.png' -c:v libx264 -pix_fmt yuv420p -crf 20 out.mp4
"""
import os, sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.abspath(sys.argv[1]); OUT = os.path.abspath(sys.argv[2]); PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 8733
os.makedirs(OUT, exist_ok=True)


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def do_POST(self):
        if not self.path.startswith("/frame/"):
            self.send_response(404); self.end_headers(); return
        name = os.path.basename(self.path)
        if not name.endswith(".png") or "/" in name or ".." in name:
            self.send_response(400); self.end_headers(); return
        n = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(n)
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(data)
        self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"serving {ROOT} on http://127.0.0.1:{PORT}  frames -> {OUT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
