from __future__ import annotations

__all__ = ["BaseEventHandler", "EventHandler", "EventListener"]

import collections
import concurrent.futures as cfutures
import contextlib
import itertools
import threading
import weakref
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Generic,
    Iterable,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
)

from classy_decorators import Decorator

from ._utils import TypeMROMap

T = TypeVar("T")
ET = TypeVar("ET")  # event type
FT = TypeVar("FT", bound=Callable[..., Any])

HT = TypeVar("HT", bound="BaseEventHandler")  # noqa
HT_co = TypeVar("HT_co", bound="BaseEventHandler", covariant=True)  # noqa
LT = TypeVar("LT", bound="EventListener")  # noqa


class EventListener(Decorator[Any, FT], Generic[ET, FT, HT]):
    def __init__(
        self: LT,
        function: FT,
        *,
        handler: HT,
        events: Iterable[ET],
        unique: bool = False,
        _registered: bool = False,
        **kwargs,
    ):
        self.handler: HT = handler
        self.events: FrozenSet[ET] = frozenset(events)
        self.unique: bool = unique

        super().__init__(
            function,
            handler=self.handler,
            events=self.events,
            unique=self.unique,
            _registered=True,
            **kwargs,
        )

        if not _registered:
            self.handler.register_listener(self)

        self.name: Optional[str] = None

        _events_repr = ", ".join(f"'{e}'" for e in self.events)
        self.__wrappername__ = f"{type(self).__name__}({_events_repr})"

    def __set__(self, *args, **kwargs):
        raise AttributeError(f"{self} is read-only")

    def __set_name__(self, owner: Type[T], name: str):
        super().__set_name__(owner, name)

        assert name == self.__name__
        self.name = name

        self.handler.register_listener_owner(self, owner, name)

    @property
    def unique_events(self) -> FrozenSet[ET]:
        if self.unique:
            return self.events
        else:
            return frozenset(
                cast(Set, self.events) & cast(Set, self.handler.unique_events)
            )

    @classmethod
    def prepare(cls: Type[LT], **kwargs) -> Callable[..., LT]:
        def _prepare(function) -> LT:
            return cls(function, **kwargs)

        return _prepare


class BaseEventHandler(Generic[LT, ET, FT]):
    """
    Subclasses can specify a custom event listener type using generics, the
    'event_listener' subclass kwarg.

    *Example*: Consider the custom event listener subclass:
    >>> class MyEventListener(EventListener):
    ...     ...

    To use this for a custom handler, you can pass the type as a generic:
    >>> class MyEventHandler(BaseEventHandler[MyEventListener]):
    ...     ...

    Or with the subclass keyword `event_listener`:
    >>> class MyEventHandler(BaseEventHandler, event_listener=MyEventListener):
    ...     ...

    Otherwise, it defaults to `EventListener`
    """

    __event_listener_type__: Type[LT] = EventListener

    def __init__(self):
        ddict = collections.defaultdict
        wset = weakref.WeakSet

        self._instances: weakref.WeakSet[T] = wset()

        self.__event_waiters: Dict[
            ET, List[Tuple[cfutures.Future, Optional[Callable[..., bool]]]]
        ] = ddict(list)
        self.__event_waiters_lock: threading.Lock = threading.Lock()

        self.__listener_functions: Dict[ET, List[LT]] = ddict(list)
        self.__listener_methods: Dict[ET, List[LT]] = ddict(list)

        self.__unique_events: Set[ET] = set()
        self.__unique_events_bound: Dict[ET, Set[T]] = ddict(set)
        self._ignored_events: Set[ET] = set()

        # type -> listener method name -> listener
        #  the default for missing owners is a chainmap child of the parent
        self.__owner_listener_map: TypeMROMap[T, LT] = TypeMROMap()

        # parent type -> list of child types
        #  the owner inheritance tree needs to be traversed down when bound
        #  instances need to be found given a parent owner of a listener
        self.__owner_child_map: Dict[Type[T], Set[Type[T]]] = ddict(set)

        # type -> weakly referenced set of instances
        self.__owner_instances: Dict[Type[T], weakref.WeakSet[T]] = ddict(wset)

    def __init_subclass__(
        cls, *, event_listener: Optional[Type[LT]] = None, **kwargs
    ):
        super().__init_subclass__()

        if event_listener:
            cls.__event_listener_type__ = event_listener

    @property
    def events(self) -> FrozenSet[ET]:
        return frozenset(
            set(self.__listener_functions) | set(self.__listener_methods)
        )

    @property
    def unique_events(self) -> FrozenSet[ET]:
        instanced_unique_events = self.__unique_events_bound
        return frozenset(
            itertools.chain(
                self.__unique_events,
                filter(
                    lambda event: instanced_unique_events[event],
                    instanced_unique_events,
                ),
            )
        )

    @property
    def listeners(self) -> Dict[ET, List[LT]]:
        """Dict of all function bound method listeners by event"""
        events: Set[ET] = cast(Set, self.events)
        return {event: list(self.get_listeners(event)) for event in events}

    def on(
        self, *events: ET, unique: bool = False, **kwargs
    ) -> Callable[[Callable], LT]:
        """
        Registers the decorated function or bound method as event listener
        for the event with name 'event'.
        Methods require their instance to be registered with 'bind'.
        """
        if not events:
            raise ValueError("no event name provided")

        return self.__event_listener_type__.prepare(
            handler=self, events=events, unique=unique, **kwargs
        )

    @contextlib.contextmanager
    def ignore_listeners(self, *events):
        """
        Temporarily ignores event dispatching to the listeners.
        """
        _events = frozenset(events)
        if duplicates := self._ignored_events & _events:
            raise ValueError(
                "events " + ", ".join(duplicates) + " already ignored"
            )

        self._ignored_events |= _events

        try:
            yield
        finally:
            self._ignored_events -= _events

    def get_future_event(
        self,
        event: ET,
        /,
        predicate: Optional[Callable[..., bool]] = None,
        **predicate_kwargs,
    ) -> cfutures.Future[Dict[ET, Any]]:
        """
        The returned future's result is set to the event kwargs when it is
        dispatched .
        If a callable is given as second argument, the result is only set if
        the predicate returns true with the event kwargs.
        Alternatively, the kwargs are used to filter the event result.

        (async would've been nice here...)
        """
        if predicate is not None and predicate_kwargs:
            raise ValueError("provide either a predicate or kwargs")

        if predicate_kwargs:

            def predicate(*_args, **_kwargs):
                for k, v in predicate_kwargs.items():
                    if _kwargs.get(k) != v:
                        return False
                return True

        future: cfutures.Future = cfutures.Future()
        with self.__event_waiters_lock:
            self.__event_waiters[event].append((future, predicate))

        future.set_running_or_notify_cancel()
        return future

    # The following methods are only to be used in the dispatcher
    def bind(self, instance: T):
        """
        Sets the instance of the registered event listener methods for the
        corresponding class.
        """
        if instance in self._instances:
            raise ValueError(f"instance {instance} already bound")

        self._instances.add(instance)

        child_count = 0
        for owner in self._get_owner_children(type(instance)):
            child_count += 1
            self.__owner_instances[owner].add(instance)

            for name, listener in self.__owner_listener_map[owner].items():
                for event in listener.unique_events:
                    for sibling in self.get_listeners(event):
                        if listener >= sibling:
                            # equal or bound sinbling and equal
                            continue

                        raise AttributeError(
                            f"duplicate event listener for unique event "
                            f"'{event}': {listener} and {sibling}"
                        )

                for event in listener.unique_events:
                    self.__unique_events_bound[event].add(instance)

        if not child_count:
            raise TypeError(
                f"type {type(instance)} has no registered events listeners"
            )

    def unbind(self, instance: T):
        if instance not in self._instances:
            return

        for owner in self._get_owner_children(type(instance)):
            self.__owner_instances[owner].remove(instance)

            for name, listener in self.__owner_listener_map[owner].items():
                if (
                    listener.is_method
                    and listener.is_bound
                    and instance is listener.__self__
                ):
                    for event in listener.unique_events:
                        self.__unique_events_bound[event].remove(instance)

        self._instances.remove(instance)

    def dispatch(self, event: ET, **kwargs) -> int:
        """
        Causes all event listener functions and bound methods for the event
        with name 'event' to be called with the provided params.
        Returns the number of called listeners.
        """
        count = self._notify_waiters(event, **kwargs)
        for listener in self.get_listeners(event):
            if event not in self._ignored_events:
                self._dispatch_listener(event, listener, **kwargs)
            count += 1
        return count

    # The following methods should be used internally only.
    def get_listeners(
        self,
        event: ET,
        owner: Optional[Union[Type[T], bool]] = None,
        bound: bool = True,
    ) -> Iterator[LT]:
        """
        Function listeners and bound method listeners for the given event.
        Optionally, yield only functions or bound methods by setting 'owner' to
        True or False, respectively. If a type is passed to owner, only methods
        bound to instances of that type are yielded.
        """
        event_owners: Iterable[Type[T]]
        if owner is None or owner is False:
            for listener_function in self.__listener_functions[event]:
                yield listener_function

        if owner is False:
            return

        if owner is None or isinstance(owner, bool):
            event_owners = self._get_event_owners(event)
        else:
            event_owners = [owner]

        for event_owner in self._get_owner_children(*event_owners):
            for listener in self._get_owner_listeners(event, event_owner):
                assert issubclass(event_owner, listener.owner)

                if bound:
                    for instance in self.__owner_instances[event_owner].copy():
                        assert isinstance(instance, event_owner)

                        yield listener.__get__(instance, type(instance))
                else:
                    yield listener

    def register_listener(self, listener: LT):
        if listener.is_method:
            listeners = self.__listener_methods
        else:
            if listener.unique:
                self.__unique_events.update(cast(Set, listener.events))

            for unique_event in listener.unique_events:
                if double_listeners := list(self.get_listeners(unique_event)):
                    raise AttributeError(
                        f"event '{unique_event}' is unique but has multiple "
                        f"listeners: "
                        + ", ".join(
                            l.__qualname__ for l in double_listeners  # noqa
                        )
                        + " and "
                        + listener.__qualname__
                    )

            listeners = self.__listener_functions

        for event in listener.events:
            listeners[event].append(listener)

    def register_listener_owner(self, listener: LT, owner: Type[T], name: str):
        if name in self.__owner_listener_map:  # pragma: no cover
            raise KeyError(f"listener '{name}' already registered for {owner}")
        self.__owner_listener_map[owner][name] = listener

        owner_parent = owner.mro()[1]
        if owner_parent in self.__owner_listener_map:
            self.__owner_child_map[owner_parent].add(owner)

    def bind_owner(self, owner: Type[T]):
        _owner = owner
        for owner_parent in owner.mro()[1:]:
            if owner_parent in self.__owner_listener_map:
                self.__owner_child_map[owner_parent].add(_owner)
                _owner = owner_parent

    @property
    def _owners(self) -> FrozenSet[Type[T]]:
        return frozenset(self.__owner_listener_map.keys())

    def _notify_waiters(self, event: ET, **kwargs) -> int:
        notified = 0

        with self.__event_waiters_lock:
            if event not in self.__event_waiters:
                return 0

            for future, predicate in self.__event_waiters.pop(event):
                try:
                    if predicate is not None and not predicate(**kwargs):
                        self.__event_waiters[event].append((future, predicate))
                        continue
                except Exception as e:
                    future.set_exception(e)
                    self._handle_predicate_exception(event, e)
                    raise
                else:
                    future.set_result(kwargs)
                    notified += 1

        return notified

    def _dispatch_listener(self, event: ET, listener: LT, **kwargs):
        return listener(**kwargs)

    def _handle_predicate_exception(self, event: ET, exception: BaseException):
        ...  # pragma: no cover

    def _get_owner_listeners(self, event: ET, owner: Type[T]) -> Iterator[LT]:
        _names = set()
        for name, listener in self.__owner_listener_map[owner].items():
            assert name not in _names  # should not happen in chainmaps
            _names.add(name)

            if event in listener.events:
                yield listener

    def _get_event_owners(self, event: ET) -> Iterator[Type[T]]:
        _owners = set()
        for listener in self.__listener_methods[event]:
            if (owner := listener.owner) is None:
                continue  # pragma: no cover

            if owner in _owners:
                continue

            _owners.add(owner)
            yield listener.owner

    def _get_owner_children(self, *owners: Type[T]) -> Iterator[Type[T]]:
        seen = set()
        queue = collections.deque(owners)
        while queue:
            if (child_owner := queue.popleft()) in seen:
                continue

            seen.add(child_owner)
            queue.extend(self.__owner_child_map[child_owner])

            yield child_owner


EventHandler = BaseEventHandler[EventListener[ET, FT, HT_co], ET, FT]
EventHandler.__doc__ = """
    Alias of BaseEventHandler, for direct use, e.g.:

    >>> str_events = EventHandler[str]()
    """
