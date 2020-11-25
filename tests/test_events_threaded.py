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
