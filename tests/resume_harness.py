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
from collections.abc import Callable
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
        # Counted per (display_type, key): ship ids are their own kind of page.
        self.counts: dict[tuple[str, str], int] = {}
        self.block_id: int | None = None
        self.block_active = False
        self.block_limit: int | None = None  # stop blocking after this many hits
        self.drop_ships = False  # close ship-page connections without answering
        self.hang_secs = 0.0  # answer ship pages only after this long
        self.blocked: set[tuple[str, str]] = set()  # (display_type, key) answered with 429
        # Action-crawl blocks (Task A7): one action page, or one index page.
        self.action_block_id: int | None = None
        self.action_block_active = False
        self.action_block_limit: int | None = None
        self.action_block_page: int | None = None
        self._lock = threading.Lock()

        # display_type -> handler. Each Part B adds its own handlers with
        # add_get_handler / add_post_handler, never by editing these.
        self.get_handlers: dict[str, Callable] = {"show_ship": self._serve_ship}
        self.post_handlers: dict[str, Callable] = {"select_capture": self._serve_captures}

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
                    display_type = (query.get("display_type") or [""])[0]
                    handler = outer.get_handlers.get(display_type)
                    if handler is not None:
                        handler(self, query)
                        return
                self._send(404, b"not found")

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                query = parse_qs(urlparse(self.path).query)
                display_type = (query.get("display_type") or [""])[0]
                handler = outer.post_handlers.get(display_type)
                if handler is None:
                    self._send(404, b"not found")
                    return
                handler(self, query, body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def add_get_handler(self, display_type: str, handler: Callable) -> None:
        self.get_handlers[display_type] = handler

    def add_post_handler(self, display_type: str, handler: Callable) -> None:
        self.post_handlers[display_type] = handler

    def _count(self, display_type: str, key) -> None:
        with self._lock:
            marker = (display_type, str(key))
            self.counts[marker] = self.counts.get(marker, 0) + 1

    def _serve_ship(self, h, query):
        td_id = int(query.get("id", ["0"])[0])
        self._count("show_ship", td_id)
        with self._lock:
            blocked = (self.block_active and td_id == self.block_id) or (
                ("show_ship", str(td_id)) in self.blocked
            )
            if blocked and self.block_limit is not None:
                self.block_limit -= 1
                self.block_active = self.block_limit > 0
        if self.hang_secs:
            time.sleep(self.hang_secs)
        if self.drop_ships:  # like a dead network: no response at all
            h.close_connection = True
        elif blocked:
            h._send(429, b"<html>Too Many Requests</html>")
        elif td_id in self.ship_ids:
            h._send(200, SHIP_PAGE.format(td_id=td_id).encode())
        else:
            h._send(200, NOT_FOUND_PAGE.encode())

    def _serve_captures(self, h, query, body):
        # The captures form lists every ship id as captured (no captor link).
        self._count("select_capture", "all")
        rows = "".join(CAPTURES_ROW.format(td_id=i) for i in sorted(self.ship_ids))
        html = f"<html><body><div id='datacol'><table id='capture_list'>{rows}"
        h._send(200, f"{html}</table></div></body></html>".encode())

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
            return sum(n for (dt, _key), n in self.counts.items() if dt == "show_ship")

    def count(self, td_id: int) -> int:
        with self._lock:
            return self.counts.get(("show_ship", str(td_id)), 0)

    def count_page(self, display_type: str, key) -> int:
        with self._lock:
            return self.counts.get((display_type, str(key)), 0)


ACTION_PAGE = """<!DOCTYPE html>
<html><head><title>Action {action_id}</title></head><body>
<div id="datacol">
<h1 class="column8 float_left">Action {action_id}</h1>
<div class="column8"><strong>1<sup>st</sup> January 1700<br /></strong></div>
<table id="table_action_info">
<thead><tr><th>&nbsp;</th></tr></thead>
<tbody>
<tr><th colspan="4"><h2>
<a href="index.php?display_type=show_nation&amp;id=1">Great Britain</a></h2></th></tr>
<tr><th class="column2 alpha">Ship Name</th><th class="column3">Commander</th>
<th class="column3">Notes</th></tr>
<tr><td class="column2 alpha"><span class="hidden">Name : </span>
<a href="index.php?display_type=show_ship&amp;id=42" class="shiplink">Ship One (74)</a></td>
<td class="column3">&nbsp;</td><td class="column3">note</td></tr>
</tbody>
</table>
</div>
<span id="copywrite_message">Copyright &copy; Cy Harrison</span>
</body></html>"""

ACTION_FIND_PAGE = (
    "<!DOCTYPE html><html><head><title>Find an action</title></head><body>"
    "<div id='datacol'><h1>Find an action</h1></div>"
    "<span id='copywrite_message'>Copyright &copy; Cy Harrison</span></body></html>"
)


def add_action_routes(site, action_ids):
    """Serve the action index and action pages on ``site`` (Task A7)."""
    ids = sorted(action_ids)
    per_page = 50
    pages = max(1, (len(ids) + per_page - 1) // per_page)

    def index_page(page):
        start = (page - 1) * per_page
        chunk = ids[start : start + per_page]
        rows = "".join(
            '<tr><td class="col_battle_dates"><span title="1st January 1700">1.1.1700</span></td>'
            f'<td class="col_battle"><a href="index.php?display_type=show_battle&amp;id={i}">'
            f"Action {i}</a></td>"
            '<td class="col_action_type">Fleet action</td><td class="col_war"></td></tr>'
            for i in chunk
        )
        return (
            "<!DOCTYPE html><html><head><title>Action Search Results</title></head><body>"
            "<div id='datacol'><form id='action_selector'></form>"
            "<table id='table_actions_list'>"
            f"<tr><th colspan='3'><h2>Action Search Results, {len(ids)} Records Found"
            "</h2></th></tr>"
            "<tr><td colspan='3'>&nbsp;</td></tr>"
            "<tr><th class='col_battle_dates'>Date</th><th class='col_battle'>Name</th>"
            "<th class='col_action_type'>Type</th><th class='cal_war'>War</th></tr>"
            f"{rows}</table><span>Showing Page {page} of {pages}</span></div>"
            "<span id='copywrite_message'>Copyright &copy; Cy Harrison</span></body></html>"
        )

    def serve_battle(h, query):
        key = (query.get("id") or ["0"])[0]
        site._count("show_battle", key)
        blocked = site.action_block_active and int(key) == site.action_block_id
        if blocked and site.action_block_limit is not None:
            site.action_block_limit -= 1
            site.action_block_active = site.action_block_limit > 0
        if blocked:
            h._send(429, b"<html>Too Many Requests</html>")
        elif int(key) in ids:
            h._send(200, ACTION_PAGE.format(action_id=int(key)).encode())
        else:  # a missing action id is a 302 to the action search
            h.send_response(302)
            h.send_header("Location", "/index.php?display_type=select_action")
            h.send_header("Content-Length", "0")
            h.end_headers()

    def serve_action_index_get(h, query):
        site._count("select_action", "get")
        h._send(200, ACTION_FIND_PAGE.encode())

    def serve_action_index_post(h, query, body):
        form = parse_qs(body.decode())
        page = int(form.get("page", ["1"])[0])
        site._count("select_action", page)
        if site.action_block_active and page == site.action_block_page:
            h._send(429, b"<html>Too Many Requests</html>")
            return
        h._send(200, index_page(page).encode())

    site.add_get_handler("show_battle", serve_battle)
    site.add_get_handler("select_action", serve_action_index_get)
    site.add_post_handler("select_action", serve_action_index_post)


FLEET_PAGE = """<!DOCTYPE html>
<html><head><title>Fleet {fleet_id}</title></head><body>
<div id="datacol">
<h1>Fleet {fleet_id}</h1>
<table class="column8">
<tr><td class="column2 alpha">Fleet Formed</td><td></td>
<td class="column1 alpha"><span title="1798">1798</span></td><td></td>
<td class="source_col column1 omega"><a href="#ref:1">ref:1</a></td></tr>
</table>
<table class="column8">
<thead><tr>
<th class="shipname_col column2 alpha">Ship</th>
<th class="column1 alpha">Joined</th>
<th class="column1 alpha">Left</th>
<th class="column2 alpha">Commander</th>
<th class="column2 alpha">Notes</th>
</tr></thead>
<tbody>
<tr><td class="column2 alpha">
<a href="index.php?display_type=show_ship&amp;id={fleet_id}" class="shiplink">Ship {fleet_id}</a>
</td><td></td>
<td class="column1 alpha"><span title="1798">1798</span></td><td></td>
<td class="column1 alpha"><span title="1798">1798</span></td>
<td class="column2 alpha">&nbsp;</td><td class="column2 alpha">note</td></tr>
</tbody>
</table>
</div>
<span id="copywrite_message">Copyright &copy; Cy Harrison</span>
</body></html>"""

FLEET_NOTFOUND_PAGE = (
    "<!DOCTYPE html><html><head><title>Fleet details</title></head><body>"
    "<div id='datacol'><table class='column8'>"
    "<tr><td class='column2 alpha'>Fleet Formed</td><td></td><td class='column1 alpha'></td></tr>"
    "<tr><td class='column2 alpha'>Fleet Disbanded</td><td></td>"
    "<td class='column1 alpha'></td></tr></table></div>"
    "<span id='copywrite_message'>Copyright &copy; Cy Harrison</span></body></html>"
)


def fleet_index_page(fleet_ids) -> str:
    """A flat-cell fleet-list index in the 3.1 markup."""
    cells = "".join(
        '<td><span title="1798">1798</span></td><td><span title="1798">1798</span></td>'
        '<td><a href="index.php?display_type=show_nation&amp;id=1">Great Britain</a></td>'
        f'<td><a href="index.php?display_type=show_fleet&amp;id={i}">Fleet {i}</a></td>'
        "<td>&nbsp;</td>"
        for i in fleet_ids
    )
    return (
        "<!DOCTYPE html><html><head><title>Fleets</title></head><body>"
        "<div id='datacol'><h1>Fleets</h1><table class='column9'><thead>"
        "<tr><th colspan='6'>Fleets</th></tr>"
        "<tr><th>Date From</th><th>Date To</th><th>Nationality</th><th>Fleet</th>"
        "<th>Fleet Commander</th></tr></thead>"
        f"<tbody>{cells}</tbody></table></div>"
        "<span id='copywrite_message'>Copyright &copy; Cy Harrison</span></body></html>"
    )


def add_fleet_routes(site, fleet_ids):
    """Serve the fleet-list index and fleet pages on ``site`` (Task FL7)."""
    ids = sorted(fleet_ids)
    site.fleet_block_id: int | None = None
    site.fleet_block_active = False
    site.fleet_block_limit: int | None = None

    def serve_fleet_index(h, query):
        site._count("show_fleetlist", "1")
        h._send(200, fleet_index_page(ids).encode())

    def serve_fleet(h, query):
        key = (query.get("id") or ["0"])[0]
        site._count("show_fleet", key)
        blocked = site.fleet_block_active and int(key) == site.fleet_block_id
        if blocked and site.fleet_block_limit is not None:
            site.fleet_block_limit -= 1
            site.fleet_block_active = site.fleet_block_limit > 0
        if blocked:
            h._send(429, b"<html>Too Many Requests</html>")
        elif int(key) in ids:
            h._send(200, FLEET_PAGE.format(fleet_id=int(key)).encode())
        else:  # a missing fleet id is the "Fleet details" shell, a 200
            h._send(200, FLEET_NOTFOUND_PAGE.encode())

    site.add_get_handler("show_fleetlist", serve_fleet_index)
    site.add_get_handler("show_fleet", serve_fleet)


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


def run_crawl(data_dir: Path, base_url: str, extra: list[str] | None = None, timeout=240,
              spider: str = "ships_all"):
    """Run one crawl to completion; return (returncode, output)."""
    proc = subprocess.Popen(
        crawl_command(spider, extra),
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


def start_crawl(data_dir: Path, base_url: str, extra: list[str] | None = None,
                spider: str = "ships_all"):
    return subprocess.Popen(
        crawl_command(spider, extra),
        cwd=str(SCRAPY_DIR),
        env=crawl_env(data_dir, base_url),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
