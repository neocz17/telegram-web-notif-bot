import json

import pytest

from webwatch.sources.base import SourceError
from webwatch.sources.html import HtmlOptions, parse_html
from webwatch.sources.libcal import LibCalSource, parse_libcal_datetime
from webwatch.sources.rss import parse_feed

from .conftest import SGT, FakeSession


def _event(id, title, **kw):
    ev = {
        "id": id, "title": title, "url": f"https://nlb.libcal.com/event/{id}",
        "date": "Sunday, October 25, 2026", "start": "3:00 PM", "end": "5:30 PM",
        "startdt": "2026-10-25 15:00:00", "location": "Jurong Library - MakeIT (Level 2)",
        "campus": "Jurong Library", "registration_enabled": False,
    }
    ev.update(kw)
    return ev


EVENTS = [
    _event(1, "Sewing Starter Session @ Jurong Library | MakeIT", registration_enabled=True, seats=12, seatsleft=5),
    _event(2, "Sewing Starter Session @ Jurong Library | MakeIT"),  # not open yet
    _event(3, "3D Starter Session @ Jurong Library | MakeIT"),  # fully booked
    _event(4, "Laser Cutting @ Jurong Library | MakeIT", registration_enabled=True, seats=20, seatsleft=0, waitlist="Wait list"),
    _event(5, "Storytime at Jurong Library"),  # drop-in
]

PAGE_NOT_OPEN = "<div>Categories: Workshop</div><div>Registrations open at 12:00 PM Saturday, October 10, 2026</div><p>Registration is required.</p>"
PAGE_FULL = "<div>Registration is required.</div><div class='alert'>Registrations are fully booked!</div>"
PAGE_DROP_IN = "<div>Come and listen to stories!</div>"


def _libcal(per_page=48, events=EVENTS):
    pages = [events[i:i + per_page] for i in range(0, len(events), per_page)]

    class PagedSession(FakeSession):
        def get(self, url, params=None, timeout=None):
            if "ajax/calendar/list" in url:
                self.calls.append((url, params))
                body = {"total_results": len(events), "perpage": per_page, "status": 1,
                        "results": pages[params["page"] - 1] if params["page"] <= len(pages) else []}
                from .conftest import FakeResponse
                return FakeResponse(json.dumps(body))
            return super().get(url, params, timeout)

    session = PagedSession({"/event/2": PAGE_NOT_OPEN, "/event/3": PAGE_FULL, "/event/5": PAGE_DROP_IN})
    src = LibCalSource({"calendar_id": 11498, "campus_id": 5748, "per_page": per_page}, session, SGT)
    return src, session


def test_libcal_statuses_from_json_and_event_pages():
    src, _ = _libcal()
    items = {i.id: i for i in src.fetch()}
    for item in items.values():
        src.enrich(item)
    assert items["1"].status == "open" and "Seats left: 5/12" in items["1"].details
    assert items["2"].status == "not_open"
    assert items["2"].remind_at.isoformat() == "2026-10-10T12:00:00+08:00"
    assert items["3"].status == "full"
    assert items["4"].status == "waitlist"
    assert items["5"].status == "drop_in"


def test_libcal_paginates_and_sends_campus_filter():
    src, session = _libcal(per_page=2)
    assert len(src.fetch()) == 5
    list_calls = [p for u, p in session.calls if "ajax" in u]
    assert [p["page"] for p in list_calls] == [1, 2, 3]
    assert all(p["camps"] == "5748" for p in list_calls)


def _campus_session(calendar_page=""):
    """Each campus returns one event whose id is the campus id."""
    from .conftest import FakeResponse

    class S(FakeSession):
        def get(self, url, params=None, timeout=None):
            self.calls.append((url, params))
            if "ajax/calendar/list" in url:
                c = params["camps"]
                body = {"total_results": 1, "results": [_event(int(c), f"Sewing @ {c}")]}
                return FakeResponse(json.dumps(body))
            if url.endswith("/calendar"):
                return FakeResponse(calendar_page)
            return FakeResponse("", 404)

    return S({})


def test_libcal_queries_each_listed_campus_separately():
    session = _campus_session()
    src = LibCalSource({"calendar_id": 11498, "campus_ids": [5748, 5766]}, session, SGT)
    assert sorted(i.id for i in src.fetch()) == ["5748", "5766"]
    assert [p["camps"] for u, p in session.calls if "ajax" in u] == ["5748", "5766"]


def test_libcal_all_campuses_reads_dropdown():
    page = """<select id="cal-dd"><option value="11498">Cal</option></select>
    <select class="form-control" id="cam-dd"><option value="">All</option>
    <option value="5748" data-cal_id="5748">Jurong Library</option>
    <option value="5766" data-cal_id="5766">Woodlands Library</option></select>"""
    session = _campus_session(page)
    src = LibCalSource({"calendar_id": 11498, "campus_ids": "all"}, session, SGT)
    assert sorted(i.id for i in src.fetch()) == ["5748", "5766"]


def test_libcal_all_campuses_errors_if_dropdown_missing():
    src = LibCalSource({"calendar_id": 11498, "campus_ids": "all"}, _campus_session("<html></html>"), SGT)
    with pytest.raises(SourceError):
        src.fetch()


def test_libcal_unexpected_shape_raises():
    session = FakeSession({"ajax/calendar/list": json.dumps({"error": "nope"})})
    src = LibCalSource({"calendar_id": 1}, session, SGT)
    with pytest.raises(SourceError):
        src.fetch()


def test_parse_libcal_datetime():
    dt = parse_libcal_datetime("9:30 AM Monday, November 2, 2026", SGT)
    assert (dt.month, dt.day, dt.hour, dt.minute) == (11, 2, 9, 30)
    assert parse_libcal_datetime("sometime soon", SGT) is None


def test_html_source_parses_cards():
    page = """
    <div class="card"><a href="/p/1"><h3 class="name">Blue Tote</h3></a><span class="price">$10</span></div>
    <div class="card"><a href="/p/2"><h3 class="name">Red Tote</h3></a><span class="price">$12</span></div>
    """
    opts = HtmlOptions(url="https://shop.example/new", item_selector=".card", title=".name", fields={"price": ".price"})
    items = parse_html(page, opts)
    assert [i.title for i in items] == ["Blue Tote", "Red Tote"]
    assert items[0].url == "https://shop.example/p/1"
    assert items[0].fields["price"] == "$10"
    assert items[0].id != items[1].id


def test_html_source_errors_when_selector_matches_nothing():
    opts = HtmlOptions(url="https://x.example", item_selector=".gone")
    with pytest.raises(SourceError):
        parse_html("<div class='card'></div>", opts)


def test_rss_parses_items():
    feed = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
    <item><title>Night market</title><link>https://e.example/1</link><guid>g1</guid></item>
    <item><title>Big sale</title><link>https://e.example/2</link></item>
    </channel></rss>"""
    items = parse_feed(feed)
    assert [(i.id, i.title) for i in items] == [("g1", "Night market"), ("https://e.example/2", "Big sale")]
