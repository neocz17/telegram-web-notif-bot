from webwatch.models import Item
from webwatch.runner import RunResult, process_watcher
from webwatch.state import empty_watcher_state

from .conftest import ListSource, RecordingNotifier, at


def _run(watcher, settings, wstate, items=None, error=None, now=None, notifier=None):
    notifier = notifier or RecordingNotifier()
    result = RunResult()
    new_state = process_watcher(
        watcher, wstate, ListSource(items, error), notifier, settings, now or at(2026, 10, 5, 12), result
    )
    return new_state, notifier, result


def test_first_run_is_a_single_baseline_message(watcher, settings):
    items = [Item(id=str(i), title=f"Event {i}") for i in range(3)]
    state, notifier, _ = _run(watcher, settings, empty_watcher_state(), items)
    assert len(notifier.sent) == 1
    assert "Now watching" in notifier.sent[0]
    assert state["initialized"] and set(state["items"]) == {"0", "1", "2"}


def test_only_new_items_are_notified(watcher, settings):
    state, _, _ = _run(watcher, settings, empty_watcher_state(), [Item(id="a", title="Old")])
    state, notifier, _ = _run(watcher, settings, state, [Item(id="a", title="Old"), Item(id="b", title="Brand new")])
    assert len(notifier.sent) == 1
    assert "Brand new" in notifier.sent[0] and "Old" not in notifier.sent[0]

    _, notifier, _ = _run(watcher, settings, state, [Item(id="a", title="Old"), Item(id="b", title="Brand new")])
    assert notifier.sent == []  # nothing changed -> no messages


def test_status_going_up_alerts_but_going_down_does_not(watcher, settings):
    state, _, _ = _run(watcher, settings, empty_watcher_state(), [Item(id="a", title="Sewing", status="not_open")])

    state, notifier, _ = _run(watcher, settings, state, [Item(id="a", title="Sewing", status="open")])
    assert len(notifier.sent) == 1 and "OPEN" in notifier.sent[0]

    state, notifier, _ = _run(watcher, settings, state, [Item(id="a", title="Sewing", status="waitlist")])
    assert notifier.sent == []  # open -> waitlist means it filled up: no alert

    _, notifier, _ = _run(watcher, settings, state, [Item(id="a", title="Sewing", status="open")])
    assert len(notifier.sent) == 1  # a seat freed up again


def test_reminder_sent_once_inside_window(watcher, settings):
    opens = at(2026, 10, 10, 12, 0)
    item = Item(id="a", title="Sewing", status="not_open", remind_at=opens, remind_text="Registration opens at noon")
    state, _, _ = _run(watcher, settings, empty_watcher_state(), [item], now=at(2026, 10, 9, 12))

    state, notifier, _ = _run(watcher, settings, state, [item], now=at(2026, 10, 10, 10, 0))
    assert notifier.sent == []  # 2h before: too early

    state, notifier, _ = _run(watcher, settings, state, [item], now=at(2026, 10, 10, 11, 15))
    assert len(notifier.sent) == 1 and "in ~45 min" in notifier.sent[0]

    _, notifier, _ = _run(watcher, settings, state, [item], now=at(2026, 10, 10, 11, 30))
    assert notifier.sent == []  # already reminded


def test_failed_notification_keeps_old_state_for_retry(watcher, settings):
    state, _, _ = _run(watcher, settings, empty_watcher_state(), [Item(id="a", title="A")])
    items = [Item(id="a", title="A"), Item(id="b", title="B")]
    kept, _, result = _run(watcher, settings, state, items, notifier=RecordingNotifier(fail=True))
    assert kept == state and result.notify_failed == ["test"]

    _, notifier, _ = _run(watcher, settings, kept, items)
    assert len(notifier.sent) == 1 and "B" in notifier.sent[0]  # retried


def test_failure_alert_after_threshold_then_recovery(watcher, settings):
    state, _, _ = _run(watcher, settings, empty_watcher_state(), [Item(id="a", title="A")])
    sent = []
    for _ in range(4):
        state, notifier, _ = _run(watcher, settings, state, error=RuntimeError("site down"))
        sent += notifier.sent
    assert len(sent) == 1 and "failing" in sent[0]  # alerted exactly once (on the 3rd failure)
    assert state["consecutive_failures"] == 4 and state["items"]  # items not lost

    state, notifier, _ = _run(watcher, settings, state, [Item(id="a", title="A")])
    assert len(notifier.sent) == 1 and "recovered" in notifier.sent[0]
    assert state["consecutive_failures"] == 0


def test_items_that_briefly_disappear_are_not_new_again(watcher, settings):
    state, _, _ = _run(watcher, settings, empty_watcher_state(), [Item(id="a", title="A")], now=at(2026, 10, 1))
    state, _, _ = _run(watcher, settings, state, [], now=at(2026, 10, 2))
    _, notifier, _ = _run(watcher, settings, state, [Item(id="a", title="A")], now=at(2026, 10, 3))
    assert notifier.sent == []

    state, _, _ = _run(watcher, settings, state, [], now=at(2026, 11, 1))
    assert "a" not in state["items"]  # forgotten after forget_after_days


def test_filters(settings):
    from webwatch.config import WatcherConfig

    w = WatcherConfig(
        name="f", type="html",
        filters={"include": "(?i)sew", "exclude": "Kids", "fields": {"location": "Jurong"}},
    )
    items = [
        Item(id="1", title="Sewing Starter", fields={"location": "Jurong Library"}),
        Item(id="2", title="Sewing for Kids", fields={"location": "Jurong Library"}),
        Item(id="3", title="Sewing Starter", fields={"location": "Tampines Library"}),
        Item(id="4", title="3D Printing", fields={"location": "Jurong Library"}),
    ]
    state, _, _ = _run(w, settings, empty_watcher_state(), items)
    assert list(state["items"]) == ["1"]
