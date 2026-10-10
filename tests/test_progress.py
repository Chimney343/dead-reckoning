"""Progress bars and the ETA model behind ``python -m fetch get``."""

from __future__ import annotations

import httpx
import pytest
import respx

from fetch import core, progress, run
from fetch.manifest import Entry
from fetch.progress import EtaModel, Plan, ProgressReporter, fmt_duration

MB = 1024 * 1024


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += seconds


def make_entry(**kwargs) -> Entry:
    base = dict(
        id="x", group="wrecks", title="t", resolver="direct",
        licence="CC-BY-4.0", tier="T1", status="verified",
    )
    base.update(kwargs)
    return Entry(**base)


def stream(model: EtaModel, clock: Clock, entry_id: str, size: int, secs: float, gap: float):
    """One source: ``gap`` seconds of overhead, then ``size`` bytes over ``secs``."""
    model.start_entry(entry_id)
    clock.tick(gap)
    model.file_start(size, 0)
    clock.tick(secs)
    model.advance(size)
    model.file_end()
    model.finish_entry()


# --- formatting -----------------------------------------------------------


def test_fmt_duration():
    assert fmt_duration(None) == "?"
    assert fmt_duration(75) == "0:01:15"
    assert fmt_duration(3 * 3600 + 5) == "3:00:05"
    assert fmt_duration(86400 + 3661) == "1d 1:01:01"


# --- the ETA model --------------------------------------------------------


def test_eta_is_unknown_until_a_rate_is_measured():
    clock = Clock()
    model = EtaModel([Plan("a", "file", 10 * MB), Plan("b", "file", 10 * MB)], clock)
    assert model.eta_secs() is None
    model.start_entry("a")
    assert model.eta_secs() is None


def test_eta_with_nothing_left_to_download_is_overhead_only():
    clock = Clock()
    model = EtaModel([Plan("a", "file", 0), Plan("b", "file", 0)], clock)
    assert model.eta_secs() == 2 * progress.DEFAULT_OVERHEAD["file"]


def test_eta_combines_rate_and_measured_overhead():
    clock = Clock()
    plans = [Plan("a", "file", 10 * MB), Plan("b", "file", 10 * MB), Plan("c", "file", 20 * MB)]
    model = EtaModel(plans, clock)
    stream(model, clock, "a", 10 * MB, secs=10, gap=4)  # 1 MB/s, 4 s overhead
    assert model.byte_rate() == MB
    assert model.overhead("file") == 4
    # b and c still to come: 30 MB at 1 MB/s plus two sources at 4 s each.
    assert model.eta_secs() == 30 + 2 * 4


def test_eta_counts_only_the_unfinished_part_of_the_current_file():
    clock = Clock()
    model = EtaModel([Plan("a", "file", 10 * MB), Plan("b", "file", 10 * MB)], clock)
    stream(model, clock, "a", 10 * MB, secs=10, gap=0)
    model.start_entry("b")
    model.file_start(10 * MB, 0)
    clock.tick(4)
    model.advance(4 * MB)
    assert model.remaining_bytes() == 6 * MB


def test_the_content_length_beats_a_wrong_manifest_size():
    clock = Clock()
    model = EtaModel([Plan("a", "file", 1 * MB)], clock)
    model.start_entry("a")
    model.file_start(50 * MB, 0)  # the manifest said 1 MB
    assert model.remaining_bytes() == 50 * MB


def test_a_resumed_file_does_not_count_the_bytes_already_on_disk():
    clock = Clock()
    model = EtaModel([Plan("a", "file", 10 * MB)], clock)
    model.start_entry("a")
    model.file_start(10 * MB, resume_from=6 * MB)
    assert model.remaining_bytes() == 4 * MB


def test_harvesters_have_their_own_overhead_and_no_bytes():
    clock = Clock()
    plans = [Plan("h1", "harvest", 0), Plan("h2", "harvest", 0), Plan("f", "file", 0)]
    model = EtaModel(plans, clock)
    model.start_entry("h1")
    clock.tick(120)
    model.finish_entry()
    # h2 is expected to cost what h1 did; the file source keeps its default.
    assert model.overhead("harvest") == 120
    assert model.eta_secs() == 120 + progress.DEFAULT_OVERHEAD["file"]


def test_the_rate_counts_the_time_of_the_file_in_flight():
    clock = Clock()
    model = EtaModel([Plan("a", "file", 10 * MB)], clock)
    model.start_entry("a")
    model.file_start(10 * MB, 0)
    clock.tick(4)
    model.advance(4 * MB)  # 1 MB/s so far; the file has not ended yet
    assert model.byte_rate() == MB


def test_a_tiny_sample_is_not_trusted_as_a_rate():
    clock = Clock()
    model = EtaModel([Plan("a", "file", MB), Plan("b", "file", MB)], clock)
    stream(model, clock, "a", 1024, secs=0.01, gap=0)  # huge apparent rate
    assert model.byte_rate() is None


# --- plans ----------------------------------------------------------------


def test_plans_weight_downloaded_sources_at_zero_and_unknown_at_the_median(tmp_path):
    done = make_entry(id="done", approx_bytes=5 * MB)
    new = make_entry(id="new", approx_bytes=7 * MB)
    unknown = make_entry(id="unknown", approx_bytes=0)
    (tmp_path / "done").mkdir()
    (tmp_path / "done" / "d.csv").write_bytes(b"x")
    core.write_provenance(tmp_path / "done" / "_provenance.json", {"files": {"d.csv": {}}})

    by_id = {p.id: p for p in progress.make_plans([done, new, unknown], tmp_path)}
    assert by_id["done"].weight == 0
    assert by_id["new"].weight == 7 * MB
    assert by_id["unknown"].weight == 6 * MB  # median of the known sizes

    forced = {p.id: p for p in progress.make_plans([done], tmp_path, force=True)}
    assert forced["done"].weight == 5 * MB


def test_harvesters_are_planned_as_overhead_not_bytes(tmp_path):
    entry = make_entry(id="w", resolver="wikidata", approx_bytes=9 * MB)
    (plan,) = progress.make_plans([entry], tmp_path)
    assert (plan.kind, plan.weight) == ("harvest", 0)


# --- the reporter, and the events core emits ------------------------------


class Recorder(core.NullReporter):
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def file_start(self, filename, total, resume_from=0):
        self.events.append(("start", filename, total, resume_from))

    def advance(self, n):
        self.events.append(("advance", n))

    def file_end(self):
        self.events.append(("end",))


@respx.mock
def test_download_file_reports_start_chunks_and_end(tmp_path):
    body = b"a" * 1000
    respx.get("https://example.org/d.csv").mock(return_value=httpx.Response(200, content=body))
    spec = core.FileSpec(urls=["https://example.org/d.csv"], filename="d.csv")
    recorder = Recorder()
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        core.download_file(client, spec, tmp_path, reporter=recorder)
    assert recorder.events[0] == ("start", "d.csv", 1000, 0)
    assert sum(e[1] for e in recorder.events if e[0] == "advance") == 1000
    assert recorder.events[-1] == ("end",)


@respx.mock
def test_download_file_reports_the_resume_offset(tmp_path):
    (tmp_path / "d.csv.part").write_bytes(b"a" * 600)
    respx.get("https://example.org/d.csv").mock(
        return_value=httpx.Response(206, content=b"b" * 400)
    )
    spec = core.FileSpec(urls=["https://example.org/d.csv"], filename="d.csv")
    recorder = Recorder()
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        core.download_file(client, spec, tmp_path, reporter=recorder)
    assert recorder.events[0] == ("start", "d.csv", 1000, 600)


class BrokenStream(httpx.SyncByteStream):
    def __iter__(self):
        yield b"abc"
        raise httpx.ReadError("connection lost")


@respx.mock
def test_a_stream_that_breaks_still_ends_the_file(tmp_path):
    respx.get("https://example.org/d.csv").mock(
        return_value=httpx.Response(200, headers={"content-length": "10"}, stream=BrokenStream())
    )
    spec = core.FileSpec(urls=["https://example.org/d.csv"], filename="d.csv")
    recorder = Recorder()
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        with pytest.raises(httpx.ReadError):
            core.download_file(client, spec, tmp_path, reporter=recorder)
    # httpx hands over whole 256 KB chunks, so the 3 buffered bytes are lost with the error.
    assert recorder.events == [("start", "d.csv", 10, 0), ("end",)]
    assert (tmp_path / "d.csv.part").exists()  # kept, so the next run resumes


@respx.mock
def test_fetch_entries_with_progress_downloads_both_sources(tmp_path, capsys):
    respx.get("https://example.org/one.csv").mock(
        return_value=httpx.Response(200, content=b"a,b\n" * 1000)
    )
    respx.get("https://example.org/two.csv").mock(
        return_value=httpx.Response(200, content=b"c,d\n" * 1000)
    )
    entries = [
        make_entry(id="one", url="https://example.org/one.csv", filename="one.csv",
                   approx_bytes=4000),
        make_entry(id="two", url="https://example.org/two.csv", filename="two.csv",
                   approx_bytes=4000),
    ]
    lines: list[str] = []
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        results = run.fetch_entries(entries, client, tmp_path, progress=True, log=lines.append)
    # The plan is logged before the bars start; later lines go through tqdm.write.
    assert lines and "2 source(s) to download:" in lines[0]
    assert "fetch  one [wrecks/direct]" in capsys.readouterr().out
    assert [r["id"] for r in results] == ["one", "two"]
    assert (tmp_path / "two" / "two.csv").read_bytes() == b"c,d\n" * 1000


def test_reporter_advances_the_source_count_and_reaches_done(tmp_path):
    clock = Clock()
    entries = [make_entry(id="a", approx_bytes=MB), make_entry(id="b", approx_bytes=MB)]
    reporter = ProgressReporter(entries, tmp_path, clock=clock, disable=True)
    for entry in entries:
        reporter.entry_start(entry)
        reporter.file_start("f.csv", MB, 0)
        clock.tick(3)
        reporter.advance(MB)
        reporter.file_end()
        reporter.entry_done()
    assert reporter.model.done == 2
    assert reporter.model.eta_secs() == 0
    reporter.close()


@respx.mock
def test_dry_run_with_progress_creates_no_bars(tmp_path):
    respx.get("https://example.org/one.csv")  # never called
    entry = make_entry(id="one", url="https://example.org/one.csv", filename="one.csv")
    lines: list[str] = []
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        results = run.fetch_entries(
            [entry], client, tmp_path, progress=True, dry_run=True, log=lines.append
        )
    assert results[0]["status"] == "dry-run"
