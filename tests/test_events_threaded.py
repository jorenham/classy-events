import time

from classy_events import events_threaded as events


def test_synced_events():
    event_handler = events.SyncedEventHandler()

    @event_handler.on("spam")
    def spam(items):
        items.append("eggs")

    things = []
    assert event_handler.dispatch("spam", items=things) == 1
    assert "eggs" in things


def test_threaded_events():
    event_handler = events.ThreadedEventHandler()

    @event_handler.on("spam")
    def spam(items):
        items.append("eggs")

    things = []
    assert event_handler.dispatch("spam", items=things) == 1
    assert "eggs" in things


def test_threaded_events_defer():
    event_handler = events.ThreadedEventHandler()

    @event_handler.on("spam", deferred=True)
    def spam(items):
        time.sleep(1)
        items.append("eggs")

    things = []
    assert event_handler.dispatch("spam", items=things) == 1
    assert not things

    t0 = time.time()
    event_handler.wait()
    dt = time.time() - t0

    assert .9 < dt < 1.1

    assert "eggs" in things
