import time

import pytest

from classy_events import events_threaded as events


@pytest.fixture
def event_handler(request):
    return events.ThreadedEventHandler()


def test_defer(event_handler):
    @event_handler.on("spam", deferred=True)
    def spam(items):
        time.sleep(0.2)
        items.append("eggs")

    things = []
    assert event_handler.dispatch("spam", items=things) == 1
    assert not things

    t0 = time.time()
    event_handler.wait()
    dt = time.time() - t0

    assert 0.1 < dt < 0.3

    assert "eggs" in things


def test_collect(event_handler):
    @event_handler.on("spam", deferred=True)
    def spam_second():
        time.sleep(0.3)
        return "second"

    @event_handler.on("spam", deferred=True)
    def spam_first():
        time.sleep(0.2)
        return "first"

    @event_handler.on("spam", deferred=True)
    def spam_third():
        time.sleep(0.4)
        raise ValueError("third")

    @event_handler.on("spam", deferred=True)
    def spam_timeout():
        time.sleep(0.6)

    assert event_handler.dispatch("spam") == 4

    t0 = time.time()
    futures = event_handler.collect_deferred(timeout=0.5)

    future_first = next(futures)
    dt_first = time.time() - t0
    assert future_first.result() == "first"

    future_second = next(futures)
    dt_second = time.time() - t0
    assert future_second.result() == "second"

    future_third = next(futures)
    dt_third = time.time() - t0
    with pytest.raises(ValueError):
        future_third.result()

    with pytest.raises(TimeoutError):
        future_fourth = next(futures)
    dt_fourth = time.time() - t0

    with pytest.raises(StopIteration):
        next(futures)

    event_handler.wait()
    dt = time.time() - t0

    assert 0.1 < dt_first < dt_second < dt_third < dt_fourth < 0.7
