from __future__ import annotations

__all__ = [
    "BaseSyncedEventHandler",
    "BaseThreadedEventHandler",
    "SyncedEventListener",
    "SyncedEventHandler",
    "ThreadedEventListener",
    "ThreadedEventHandler",
]

import concurrent.futures as cfutures
import contextlib
import logging
import threading
from collections import defaultdict as ddict
from typing import (
    Any,
    Callable,
    ContextManager,
    Dict,
    Generic,
    Iterable,
    Iterator,
    Optional,
    TypeVar,
    Union,
)

from .events import BaseEventHandler, EventListener

T = TypeVar("T")
ET = TypeVar("ET")  # event type
FT = TypeVar("FT", bound=Callable[..., Any])

LT = TypeVar("LT", bound="SyncedEventListener")  # noqa
TLT = TypeVar("TLT", bound="ThreadedEventListener")  # noqa
HT = TypeVar("HT", bound="BaseSyncedEventHandler")  # noqa
THT = TypeVar("THT", bound="BaseThreadedEventHandler")  # noqa
HT_co = TypeVar("HT_co", bound="BaseSyncedEventHandler", covariant=True)  # noqa
THT_co = TypeVar(
    "THT_co", bound="BaseThreadedEventHandler", covariant=True
)  # noqa

Lockable = ContextManager[bool]


class SyncedEventListener(EventListener[ET, FT, HT], Generic[ET, FT, HT]):
    def __init__(
        self, function, *, handler: HT, sync: Union[bool, str] = None, **kwargs
    ):
        if not isinstance(handler, BaseSyncedEventHandler):
            raise TypeError(
                f"event handler {type(handler)} is not a subclass of "
                f"{BaseSyncedEventHandler}"
            )

        super().__init__(function, handler=handler, sync=sync, **kwargs)

        self._sync_locks: Dict[ET, Lockable]
        if sync:
            if isinstance(sync, bool):
                sync_scopes = {e: str(e) for e in self.events}
            else:
                sync_scopes = {e: sync for e in self.events}

            self._sync_locks = {}
            for event, scope in sync_scopes.items():
                self._sync_locks[event] = self.handler._sync_locks[  # noqa
                    scope
                ]
                self.handler._sync_scopes[event] = scope  # noqa

        else:
            self._sync_locks = ddict(lambda: contextlib.nullcontext(True))

    def __call__(self, *args, _event: ET, **kwargs):
        with self._sync_locks[_event]:
            return super().__call__(*args, **kwargs)


ExceptionHandler = Union[Callable[[LT, ET, BaseException], None]]


class BaseSyncedEventHandler(BaseEventHandler[LT, ET, FT], Generic[LT, ET, FT]):
    """
    Syncs events with an optionally specified scopes.
    Useful when the events are dispatch in different threads.
    """

    logger = logging.getLogger("synced_event_handler")

    def __init__(self):
        super().__init__()

        self._sync_scopes: Dict[ET, str] = {}
        self._sync_locks: Dict[str, Lockable] = ddict(threading.Lock)

        self._event_lock = threading.RLock()

    def on(
        self,
        *events: ET,
        unique: bool = False,
        sync: Union[None, bool, str] = None,
        **kwargs,
    ) -> Callable[[Callable], LT]:
        """
        Decorator that transforms the decorated function or method into
        an event listener for the events with with the provided names.

        If unique=True, the decorated method can be bound only once.

        If sync=true, only one handler for this event is run at the same
        time, when false (the default), the handlers are allowed to run
        concurrently. If the value for sync is a string, the handlers syncs
        with all others with the same sync value.
        """
        return super().on(*events, unique=unique, sync=sync, **kwargs)

    def bind(self, instance: T):
        if instance in self._instances:
            raise ValueError(f"instance {instance} already bound")

        with self._event_lock:
            super().bind(instance)

    def unbind(self, instance: T):
        with self._event_lock:
            super().unbind(instance)

    def _dispatch_listener(self, event: ET, listener: LT, **kwargs):
        with self._event_lock:
            return super()._dispatch_listener(  # noqa
                event, listener, _event=event, **kwargs
            )


class ThreadedEventListener(
    SyncedEventListener[ET, FT, HT], Generic[ET, FT, HT]
):
    def __init__(
        self,
        function,
        *,
        handler: HT,
        events: Iterable[ET],
        sync: Union[bool, str] = None,
        deferred: bool = False,
        max_workers: Optional[int] = None,
        _pool=None,
        **kwargs,
    ):
        if deferred:
            if _pool is None:
                events = list(events)
                events_repr = ", ".join(map(str, events))
                _pool = cfutures.ThreadPoolExecutor(
                    max_workers=max_workers,
                    thread_name_prefix=f"{type(self).__name__}({events_repr})",
                )

        super().__init__(
            function,
            handler=handler,
            events=events,
            sync=sync,
            deferred=deferred,
            max_workers=max_workers,
            _pool=_pool,
            **kwargs,
        )

        self.deferred = deferred
        self._pool: Optional[cfutures.ThreadPoolExecutor] = _pool

        self.__lock = threading.RLock()

    def __call__(self, *args, **kwargs):
        if self.deferred:
            with self.__lock:
                return self._pool.submit(super().__call__, *args, **kwargs)
        else:
            return super().__call__(*args, **kwargs)

    def shutdown(self, wait=True):
        if not self.deferred:
            return

        with self.__lock:
            self._pool.shutdown(wait=wait)


class BaseThreadedEventHandler(
    BaseSyncedEventHandler[TLT, ET, FT], Generic[TLT, ET, FT]
):
    """
    Runs each event listener in a separate thread and cancels it after the
    event_timeout.
    """

    event_type_name_prefix: str = ""
    logger = logging.getLogger("threaded_event_handler")

    def __init__(self, max_workers_per_event=None):
        super().__init__()

        self._max_workers = max_workers_per_event

        self.__tasks = []
        self.__lock = threading.RLock()

    def on(
        self,
        *events: ET,
        unique: bool = False,
        sync: Union[None, bool, str] = None,
        deferred: bool = False,
        max_workers: Optional[int] = None,
        **kwargs,
    ) -> Callable[[Callable], LT]:
        max_workers = max_workers or self._max_workers
        return super().on(
            *events,
            unique=unique,
            sync=sync,
            deferred=deferred,
            max_workers=max_workers,
            **kwargs,
        )

    def collect_deferred(
        self, timeout: Optional[float] = None, cancelled: bool = False
    ) -> Iterator[cfutures.Future]:
        with self.__lock:
            _tasks = self.__tasks.copy()
            self.__tasks = []

        try:
            for future in cfutures.as_completed(_tasks, timeout):
                if not cancelled and future.cancelled():
                    continue
                yield future
        except cfutures.TimeoutError as e:
            raise TimeoutError from e

    def wait(self, timeout=None, shutdown_on_raise=True):
        try:
            for future in self.collect_deferred(timeout):
                future.result()
        except Exception:
            if shutdown_on_raise:
                self.shutdown(wait=False)
            raise

    def shutdown(self, wait=True):
        with self.__lock:
            for listeners in self.listeners.values():
                for listener in listeners:
                    listener.shutdown(wait=wait)

    def _dispatch_listener(
        self, event: ET, listener: ThreadedEventListener, **kwargs
    ):
        if listener.deferred:
            with self.__lock:
                try:
                    future = listener(_event=event, **kwargs)
                except RuntimeError:
                    self.logger.error(
                        "cannot dispatch events after shutdown of '%s'",
                        str(event),
                    )

                self.__tasks.append(future)
                return future
        else:
            return listener(_event=event, **kwargs)


class SyncedEventHandler(
    BaseSyncedEventHandler[SyncedEventListener[ET, FT, HT], ET, FT],
    event_listener=SyncedEventListener[ET, FT, HT],
):
    pass


class ThreadedEventHandler(
    BaseThreadedEventHandler[ThreadedEventListener[ET, FT, THT], ET, FT],
    event_listener=ThreadedEventListener[ET, FT, THT],
):
    pass
