import pytest

from classy_events import events, events_threaded


@pytest.fixture(
    params=[
        events.EventHandler,
        events_threaded.SyncedEventHandler,
        events_threaded.ThreadedEventHandler,
    ],
    ids=["EventHandler", "SyncedEventHandler", "ThreadedEventHandler"],
)
def event_handler(request):
    return request.param()


def test_function_listener_basic(event_handler):
    @event_handler.on("spam")
    def spam(items):
        items.append("eggs")

    things = []
    assert event_handler.dispatch("spam", items=things) == 1
    assert "eggs" in things


def test_function_listener_multiple(event_handler):
    @event_handler.on("spam")
    def spam(items):
        items.append("eggs")

    @event_handler.on("spam")
    def spam_two(items):
        items.append("ham")

    things = []
    assert event_handler.dispatch("spam", items=things) == 2
    assert "eggs" in things
    assert "ham" in things


def test_function_listener_unique(event_handler):
    @event_handler.on("spam")
    def spam(items):
        items.append("eggs")

    with pytest.raises(AttributeError):

        @event_handler.on("spam", unique=True)
        def spam_two(items):
            items.append("ham")


def test_method_listener_basic(event_handler):
    class Spam:
        def __init__(self, items):
            self.items = items

        @event_handler.on("spam")
        def spam(self):
            self.items.append("eggs")

    assert event_handler.dispatch("spam") == 0

    things = []
    spam = Spam(things)
    assert event_handler.dispatch("spam") == 0
    assert len(things) == 0

    event_handler.bind(spam)
    assert event_handler.dispatch("spam") == 1
    assert "eggs" in things


def test_method_listener_refererence(event_handler):
    class Spam:
        @event_handler.on("spam")
        def spam(self):
            ...

    spam = Spam()

    assert Spam in event_handler._owners
    assert spam not in event_handler._instances

    event_handler.bind(spam)
    assert spam in event_handler._instances

    del spam
    assert Spam in event_handler._owners
    assert len(event_handler._instances) == 0


def test_method_listener_rebind(event_handler):
    class Spam:
        def __init__(self, items):
            self.items = items

        @event_handler.on("spam")
        def spam(self):
            self.items.append("eggs")

    assert event_handler.dispatch("spam") == 0

    spam_things = []
    spam = Spam(spam_things)

    event_handler.bind(spam)
    assert event_handler.dispatch("spam") == 1
    assert len(spam_things) == 1
    event_handler.unbind(spam)

    assert event_handler.dispatch("spam") == 0
    assert len(spam_things) == 1

    spam_new_things = []
    spam_new = Spam(spam_new_things)

    assert event_handler.dispatch("spam") == 0
    assert len(spam_new_things) == 0

    event_handler.bind(spam_new)
    assert event_handler.dispatch("spam") == 1
    assert len(spam_things) == len(spam_new_things) == 1
    event_handler.unbind(spam_new)

    event_handler.bind(spam)
    assert event_handler.dispatch("spam") == 1
    assert len(spam_things) == 2


def test_method_listener_multiple(event_handler):
    class Spam:
        def __init__(self, items):
            self.items = items

        @event_handler.on("spam")
        def spam(self):
            self.items.append("spam")

        @event_handler.on("spam")
        def spam_two(self):
            self.items.append("spamspam")

        @event_handler.on("eggs")
        def eggs(self):
            self.items.append("eggs")

    things = []
    spam = Spam(things)
    event_handler.bind(spam)

    assert event_handler.dispatch("spam") == 2
    assert "spam" in things
    assert "spamspam" in things
    assert "eggs" not in things

    assert event_handler.dispatch("eggs") == 1
    assert "eggs" in things


def test_method_listener_unique_ok(event_handler):
    class Spam:
        @event_handler.on("spam", unique=True)
        def spam(self):
            ...

        @event_handler.on("eggs", unique=True)
        def eggs(self):
            ...

    spam = Spam()
    event_handler.bind(spam)
    assert True  # no exception raised


def test_method_listener_unique_error(event_handler):
    class Spam:
        @event_handler.on("spam", unique=True)
        def spam(self):
            ...

        @event_handler.on("spam", unique=True)
        def spam_two(self):
            ...

    spam = Spam()

    with pytest.raises(AttributeError):
        event_handler.bind(spam)


def test_method_listener_inheritance(event_handler):
    class Spam:
        def __init__(self, items):
            self.items = items

        @event_handler.on("spam")
        def spam(self):
            self.items.append("spam")

        @event_handler.on("eggs", unique=True)
        def eggs(self):
            self.items.append("eggs")

    class Bacon:
        def __init__(self, items):
            self.items = items

        @event_handler.on("bacon")
        def bacon(self):
            self.items.append("bacon")

    class Ham(Spam, Bacon):
        @event_handler.on("spam")
        def spam(self):
            self.items.append("hamspam")

    event_handler.bind_owner(Ham)

    things = []
    ham = Ham(things)
    event_handler.bind(ham)

    assert event_handler.dispatch("spam") == 1, things
    assert "hamspam" in things

    assert event_handler.dispatch("eggs") == 1
    assert "eggs" in things

    assert event_handler.dispatch("bacon") == 1
    assert "bacon" in things


def test_combined_listeners(event_handler):
    @event_handler.on("spam")
    def spam(items):
        items.append("spam_function")

    @event_handler.on("eggs")
    def eggs(items):
        items.append("eggs_function")

    class Spam:
        def __init__(self, items):
            self.items = items

        @event_handler.on("spam")
        def spam(self, **_):
            self.items.append("spam_method")

        @event_handler.on("ham")
        def ham(self):
            self.items.append("ham_method")

    things = []
    _spam = Spam(things)
    event_handler.bind(_spam)

    assert event_handler.dispatch("spam", items=things) == 2
    assert len(things) == 2
    assert "spam_function" in things
    assert "spam_method" in things

    assert event_handler.dispatch("eggs", items=things) == 1
    assert len(things) == 3
    assert "eggs_function" in things

    assert event_handler.dispatch("ham") == 1
    assert len(things) == 4
    assert "ham_method" in things


def test_combined_listeners_unqiue_ok(event_handler):
    @event_handler.on("eggs", unique=True)
    def eggs():
        ...

    class Spam:
        @event_handler.on("spam", unique=True)
        def spam(self):
            ...

    spam = Spam()
    event_handler.bind(spam)
    assert True  # no exception raised


def test_combined_listeners_unqiue_error_at_bind(event_handler):
    @event_handler.on("spam", unique=True)
    def spam_function():
        ...

    class Spam:
        @event_handler.on("spam", unique=True)
        def spam_method(self):
            ...

    spam = Spam()
    with pytest.raises(AttributeError):
        event_handler.bind(spam)


def test_combined_listeners_unqiue_error_at_function(event_handler):
    class Spam:
        @event_handler.on("spam", unique=True)
        def spam_method(self):
            ...

    spam = Spam()
    event_handler.bind(spam)

    with pytest.raises(AttributeError):

        @event_handler.on("spam", unique=True)
        def spam_function():
            ...


def test_future_event(event_handler):
    class Spam:
        @event_handler.on("spam")
        def spam(self, ham):
            ...

    spam = Spam()
    event_handler.bind(spam)

    future = event_handler.get_future_event("spam", ham=True)

    assert event_handler.dispatch("spam", ham=False) == 1
    assert not future.done()

    assert event_handler.dispatch("spam", ham=True) == 2
    assert future.result() == dict(ham=True)


def test_future_event_error(event_handler):
    class Spam:
        @event_handler.on("spam")
        def spam(self, ham):
            raise RuntimeError("spam")

    spam = Spam()
    event_handler.bind(spam)

    future = event_handler.get_future_event("spam")

    with pytest.raises(RuntimeError):
        event_handler.dispatch("spam", ham="ham")

    assert future.result() == dict(ham="ham")


def test_future_event_predicate_error(event_handler):
    class Spam:
        @event_handler.on("spam")
        def spam(self, ham):
            ...

    def pred(ham):
        raise RuntimeError

    spam = Spam()
    event_handler.bind(spam)

    future = event_handler.get_future_event("spam", predicate=pred)

    with pytest.raises(RuntimeError):
        event_handler.dispatch("spam", ham="ham")

    with pytest.raises(RuntimeError):
        future.result()


def test_ignore(event_handler):
    class Spam:
        def __init__(self, items):
            self.items = items

        @event_handler.on("spam")
        def spam(self):
            self.items.append("eggs")

    spam_things = []
    spam = Spam(spam_things)

    event_handler.bind(spam)

    with event_handler.ignore_listeners("spam"):
        event_handler.dispatch("spam")

    assert not spam_things

    event_handler.dispatch("spam")
    assert spam_things
