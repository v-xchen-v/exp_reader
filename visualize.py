"""
Side-by-side episode video visualizer – compare any two experiment folders.
Usage:
    python visualize.py <folder1> <folder2> [--label1 NAME] [--label2 NAME] [--port PORT]
Then open the printed URL in your browser.
"""

import argparse
import json
import re
import http.server
import threading
import webbrowser
from pathlib import Path

PORT = 8765


def get_episodes(folder: Path):
    """Return dict of {episode_id: {mp4, summary}} for a folder.

    Auto-detects the file prefix (e.g. click_alarmclock) from mp4 filenames.
    """
    episodes = {}
    for mp4 in folder.glob("*_ep*_*.mp4"):
        m = re.match(r"(.+)_ep(\d+)_", mp4.name)
        if not m:
            continue
        prefix = m.group(1)
        ep_id = int(m.group(2))
        summary_path = folder / f"{prefix}_ep{ep_id}_summary.json"
        summary = {}
        if summary_path.exists():
            with open(summary_path) as f:
                summary = json.load(f)
        episodes[ep_id] = {"mp4": mp4.name, "summary": summary}
    return episodes


def parse_args():
    parser = argparse.ArgumentParser(description="Side-by-side episode video comparison")
    parser.add_argument("folder1", type=Path, help="First experiment folder")
    parser.add_argument("folder2", type=Path, help="Second experiment folder")
    parser.add_argument("--label1", default=None, help="Display label for folder1 (default: folder name)")
    parser.add_argument("--label2", default=None, help="Display label for folder2 (default: folder name)")
    parser.add_argument("--port", type=int, default=PORT, help=f"HTTP port (default: {PORT})")
    return parser.parse_args()


args = parse_args()
DIR1 = args.folder1.resolve()
DIR2 = args.folder2.resolve()
LABEL1 = args.label1 or DIR1.name
LABEL2 = args.label2 or DIR2.name
PORT = args.port

eps1 = get_episodes(DIR1)
eps2 = get_episodes(DIR2)

common_eps = sorted(set(eps1) & set(eps2))


def build_html():
    ep_options = "\n".join(
        f'<option value="{ep}">Episode {ep}</option>' for ep in common_eps
    )

    pairs_json = {}
    for ep in common_eps:
        d1 = eps1[ep]
        d2 = eps2[ep]
        pairs_json[ep] = {
            "left": {
                "mp4": f"/videos/1/{d1['mp4']}",
                "success": d1["summary"].get("success"),
                "steps": d1["summary"].get("steps"),
                "duration": round(d1["summary"].get("duration_sec", 0), 1),
            },
            "right": {
                "mp4": f"/videos/2/{d2['mp4']}",
                "success": d2["summary"].get("success"),
                "steps": d2["summary"].get("steps"),
                "duration": round(d2["summary"].get("duration_sec", 0), 1),
            },
        }

    pairs_js = json.dumps(pairs_json)
    label1_js = json.dumps(LABEL1)
    label2_js = json.dumps(LABEL2)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Episode Visualizer</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: system-ui, sans-serif; background: #111; color: #eee; padding: 16px; }}
  h1 {{ font-size: 1.2rem; margin-bottom: 12px; color: #fff; }}
  .controls {{ display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }}
  select {{ padding: 6px 10px; font-size: 1rem; border-radius: 6px; border: 1px solid #444;
            background: #222; color: #eee; cursor: pointer; }}
  button {{ padding: 6px 14px; font-size: 0.9rem; border-radius: 6px; border: none;
            background: #3a7bd5; color: #fff; cursor: pointer; }}
  button:hover {{ background: #2f65b5; }}
  .nav-btn {{ background: #444; }}
  .nav-btn:hover {{ background: #555; }}
  .ep-counter {{ color: #aaa; font-size: 0.9rem; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .panel {{ background: #1a1a1a; border-radius: 10px; overflow: hidden; }}
  .panel-header {{ padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; }}
  .panel-title {{ font-weight: 600; font-size: 1rem; }}
  .badge {{ padding: 3px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: 600; }}
  .success {{ background: #1e5c2f; color: #4cde7a; }}
  .failure {{ background: #5c1e1e; color: #de4c4c; }}
  .unknown {{ background: #444; color: #aaa; }}
  video {{ width: 100%; display: block; background: #000; }}
  .meta {{ padding: 8px 14px; font-size: 0.82rem; color: #999; display: flex; gap: 16px; }}
  .ep-label {{ color: #bbb; font-weight: 500; }}
</style>
</head>
<body>
<h1>Episode Visualizer &mdash; <span id="lbl1"></span> vs <span id="lbl2"></span></h1>
<div class="controls">
  <button class="nav-btn" id="prevBtn">&#8592; Prev</button>
  <select id="epSelect">{ep_options}</select>
  <button class="nav-btn" id="nextBtn">Next &#8594;</button>
  <span class="ep-counter" id="counter"></span>
  <button id="syncBtn">Sync Play</button>
</div>
<div class="grid">
  <div class="panel">
    <div class="panel-header">
      <span class="panel-title" id="panel-lbl1"></span>
      <span class="badge" id="left-badge">—</span>
    </div>
    <video id="left-video" controls></video>
    <div class="meta" id="left-meta"></div>
  </div>
  <div class="panel">
    <div class="panel-header">
      <span class="panel-title" id="panel-lbl2"></span>
      <span class="badge" id="right-badge">—</span>
    </div>
    <video id="right-video" controls></video>
    <div class="meta" id="right-meta"></div>
  </div>
</div>

<script>
const pairs = {pairs_js};
const eps = {json.dumps(common_eps)};
const label1 = {label1_js};
const label2 = {label2_js};
let idx = 0;

document.getElementById('lbl1').textContent = label1;
document.getElementById('lbl2').textContent = label2;
document.getElementById('panel-lbl1').textContent = label1;
document.getElementById('panel-lbl2').textContent = label2;

const select = document.getElementById('epSelect');
const counter = document.getElementById('counter');
const leftVideo = document.getElementById('left-video');
const rightVideo = document.getElementById('right-video');

function badge(success) {{
  if (success === true) return ['success', 'Success'];
  if (success === false) return ['failure', 'Failure'];
  return ['unknown', '?'];
}}

function loadEp(ep) {{
  const d = pairs[ep];
  leftVideo.src = d.left.mp4;
  rightVideo.src = d.right.mp4;

  const [lCls, lTxt] = badge(d.left.success);
  const [rCls, rTxt] = badge(d.right.success);
  document.getElementById('left-badge').className = 'badge ' + lCls;
  document.getElementById('left-badge').textContent = lTxt;
  document.getElementById('right-badge').className = 'badge ' + rCls;
  document.getElementById('right-badge').textContent = rTxt;

  document.getElementById('left-meta').innerHTML =
    `<span>Steps: ${{d.left.steps ?? '?'}}</span><span>Duration: ${{d.left.duration}}s</span>`;
  document.getElementById('right-meta').innerHTML =
    `<span>Steps: ${{d.right.steps ?? '?'}}</span><span>Duration: ${{d.right.duration}}s</span>`;

  counter.textContent = `${{idx + 1}} / ${{eps.length}}`;
}}

function go(newIdx) {{
  idx = Math.max(0, Math.min(eps.length - 1, newIdx));
  select.value = eps[idx];
  loadEp(eps[idx]);
}}

select.addEventListener('change', () => {{
  idx = eps.indexOf(parseInt(select.value));
  loadEp(eps[idx]);
  counter.textContent = `${{idx + 1}} / ${{eps.length}}`;
}});

document.getElementById('prevBtn').addEventListener('click', () => go(idx - 1));
document.getElementById('nextBtn').addEventListener('click', () => go(idx + 1));

document.getElementById('syncBtn').addEventListener('click', () => {{
  leftVideo.currentTime = 0;
  rightVideo.currentTime = 0;
  leftVideo.play();
  rightVideo.play();
}});

document.addEventListener('keydown', (e) => {{
  if (e.key === 'ArrowRight') go(idx + 1);
  if (e.key === 'ArrowLeft') go(idx - 1);
}});

go(0);
</script>
</body>
</html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress request logs

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            content = build_html().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(content))
            self.end_headers()
            self.wfile.write(content)

        elif path.startswith("/videos/1/"):
            fname = path[len("/videos/1/"):]
            fpath = DIR1 / fname
            self._serve_file(fpath, "video/mp4")

        elif path.startswith("/videos/2/"):
            fname = path[len("/videos/2/"):]
            fpath = DIR2 / fname
            self._serve_file(fpath, "video/mp4")

        else:
            self.send_response(404)
            self.end_headers()

    def _serve_file(self, fpath: Path, content_type: str):
        if not fpath.exists():
            self.send_response(404)
            self.end_headers()
            return
        size = fpath.stat().st_size
        range_header = self.headers.get("Range")
        if range_header:
            # Support range requests for video seeking
            m = re.match(r"bytes=(\d+)-(\d*)", range_header)
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", length)
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(fpath, "rb") as f:
                f.seek(start)
                self.wfile.write(f.read(length))
        else:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", size)
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(fpath, "rb") as f:
                self.wfile.write(f.read())


if __name__ == "__main__":
    print(f"Folder 1 ({LABEL1}): {DIR1}  ({len(eps1)} episodes)")
    print(f"Folder 2 ({LABEL2}): {DIR2}  ({len(eps2)} episodes)")
    print(f"Common episodes: {len(common_eps)}  {common_eps[:5]}{'...' if len(common_eps) > 5 else ''}")
    print(f"Starting server at http://localhost:{PORT}")
    server = http.server.HTTPServer(("localhost", PORT), Handler)
    url = f"http://localhost:{PORT}"
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
