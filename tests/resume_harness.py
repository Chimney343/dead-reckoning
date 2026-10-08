"""Local HTTP site and subprocess runner for the resume tests (Plan 6, layer 5).

The site serves a sitemap of fake ship ids, a minimal ship page per id, a
not-found page for unknown ids, and (optionally) a 429 for one id. It counts
requests per ship id so a test can assert the crawler fetched each page once.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRAPY_DIR = REPO_ROOT / "scrapers" / "threedecks"

SHIP_PAGE = """<!DOCTYPE html>
<html><head><title>Ship {td_id}</title></head><body>
<div id="datacol" class="datacol column9 omega">
  <h1 class="LaunchName">Ship {td_id}</h1>
  <table id="ship_base" class="column9">
    <thead><tr><th class="showid" colspan="3">{td_id}</th></tr></thead>
    <tbody>
      <tr><td>Nominal Guns</td><td>74</td>
        <td class="source_col"><a href="#B006">B006</a></td></tr>
      <tr><td>Nationality</td>
        <td><a href="index.php?display_type=show_nation&amp;id=1">Great Britain</a></td>
        <td class="source_col"></td></tr>
      <tr><td>Launched</td><td>1.1.1800</td>
        <td class="source_col"><a href="#B006">B006</a></td></tr>
    </tbody>
  </table>
</div>
<div class="page_footer"><span id="copywrite_message">Copyright &copy; Cy Harrison</span></div>
</body></html>"""

CAPTURES_ROW = (
    '<tr><td><span class="date_field">1800/01/01</span></td>'
    '<td><a href="index.php?display_type=show_ship&amp;id={td_id}" class="shiplink">'
    "Ship {td_id}</a></td><td>Taken by the British</td></tr>"
)

NOT_FOUND_PAGE = (
    "<!DOCTYPE html><html><head><title>Find a ship</title></head>"
    "<body><div id='datacol'></div></body></html>"
)


class FakeSite:
    def __init__(self, ship_ids):
        self.ship_ids = set(ship_ids)
        self.counts: dict[int, int] = {}
        self.block_id: int | None = None
        self.block_active = False
        self.block_limit: int | None = None  # stop blocking after this many hits
        self.drop_ships = False  # close ship-page connections without answering
        self.hang_secs = 0.0  # answer ship pages only after this long
        self._lock = threading.Lock()

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence request logging
                pass

            def _send(self, status, body: bytes, content_type="text/html; charset=utf-8"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/robots.txt":
                    self._send(200, b"User-agent: *\nAllow: /\n", "text/plain")
                    return
                if parsed.path == "/ships.xml":
                    urls = "".join(
                        f"<url><loc>{outer.base_url}/index.php?display_type=show_ship&amp;id={i}</loc></url>"
                        for i in sorted(outer.ship_ids)
                    )
                    body = (
                        '<?xml version="1.0" encoding="UTF-8"?>'
                        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                        f"{urls}</urlset>"
                    ).encode()
                    self._send(200, body, "application/xml")
                    return
                if parsed.path == "/index.php":
                    query = parse_qs(parsed.query)
                    if query.get("display_type") == ["show_ship"]:
                        td_id = int(query.get("id", ["0"])[0])
                        with outer._lock:
                            outer.counts[td_id] = outer.counts.get(td_id, 0) + 1
                            blocked = outer.block_active and td_id == outer.block_id
                            if blocked and outer.block_limit is not None:
                                outer.block_limit -= 1
                                outer.block_active = outer.block_limit > 0
                        if outer.hang_secs:
                            time.sleep(outer.hang_secs)
                        if outer.drop_ships:  # like a dead network: no response at all
                            self.close_connection = True
                        elif blocked:
                            self._send(429, b"<html>Too Many Requests</html>")
                        elif td_id in outer.ship_ids:
                            self._send(200, SHIP_PAGE.format(td_id=td_id).encode())
                        else:
                            self._send(200, NOT_FOUND_PAGE.encode())
                        return
                self._send(404, b"not found")

            def do_POST(self):
                # The captures form lists every ship id as captured (no captor link).
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                query = parse_qs(urlparse(self.path).query)
                if query.get("display_type") != ["select_capture"]:
                    self._send(404, b"not found")
                    return
                rows = "".join(
                    CAPTURES_ROW.format(td_id=i) for i in sorted(outer.ship_ids)
                )
                body = f"<html><body><div id='datacol'><table id='capture_list'>{rows}"
                self._send(200, f"{body}</table></div></body></html>".encode())

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def total_ship_requests(self) -> int:
        with self._lock:
            return sum(self.counts.values())

    def count(self, td_id: int) -> int:
        with self._lock:
            return self.counts.get(td_id, 0)


def crawl_env(data_dir: Path, base_url: str) -> dict:
    env = os.environ.copy()
    env["THREEDECKS_BASE_URL"] = base_url
    env["THREEDECKS_DATA_DIR"] = str(data_dir)
    env["THREEDECKS_CONTACT"] = "test@example.org"
    return env


def crawl_command(spider: str, extra: list[str] | None = None) -> list[str]:
    return [
        sys.executable,
        "-m",
        "scrapy",
        "crawl",
        spider,
        "-s",
        "DOWNLOAD_DELAY=0",
        "-s",
        "DOWNLOAD_DELAY_JITTER=0",
        "-s",
        "AUTOTHROTTLE_ENABLED=False",
        "-s",
        "THREEDECKS_MAX_DEPTH=0",
        "-s",
        "THREEDECKS_UPWARD_LIMIT=1",
        "-s",
        "THREEDECKS_MAX_COOLOFFS=0",
        "-s",
        "LOG_LEVEL=ERROR",
        *(extra or []),
    ]


def run_crawl(data_dir: Path, base_url: str, extra: list[str] | None = None, timeout=240):
    """Run one crawl to completion; return (returncode, output)."""
    proc = subprocess.Popen(
        crawl_command("ships_all", extra),
        cwd=str(SCRAPY_DIR),
        env=crawl_env(data_dir, base_url),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        output, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        output, _ = proc.communicate()
        raise AssertionError(f"crawl timed out; output:\n{output}")
    return proc.returncode, output


def start_crawl(data_dir: Path, base_url: str, extra: list[str] | None = None):
    return subprocess.Popen(
        crawl_command("ships_all", extra),
        cwd=str(SCRAPY_DIR),
        env=crawl_env(data_dir, base_url),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
