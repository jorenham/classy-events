from __future__ import annotations

__all__ = [
    "BaseSyncedEventHandler",
    "BaseThreadedEventHandler",
    "SyncedEventListener",
    "SyncedEventHandler",
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
    List,
    TypeVar,
    Union,
)

from .events import BaseEventHandler, EventListener

T = TypeVar("T")
ET = TypeVar("ET")  # event type
FT = TypeVar("FT", bound=Callable[..., Any])

LT = TypeVar("LT", bound="SyncedEventListener")  # noqa
HT = TypeVar("HT", bound="BaseSyncedEventHandler")  # noqa
HT_co = TypeVar("HT_co", bound="BaseSyncedEventHandler", covariant=True)  # noqa

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

    __event_listener_type__ = SyncedEventListener

    logger = logging.getLogger("synced_event_handler")

    def __init__(self):
        super().__init__()

        self._exception_handlers: List[ExceptionHandler] = []

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

    def on_exception(self, fn: ExceptionHandler) -> ExceptionHandler:
        self._exception_handlers.append(fn)
        return fn

    def bind(self, instance: T):
        if instance in self._instances:
            raise ValueError(f"instance {instance} already bound")

        with self._event_lock:
            super().bind(instance)

    def unbind(self, instance: T):
        with self._event_lock:
            super().unbind(instance)

    def _dispatch_listener(self, event: ET, listener: LT, **kwargs):
        try:
            with self._event_lock:
                return super()._dispatch_listener(  # noqa
                    event, listener, _event=event, **kwargs
                )
        except Exception as e:
            self._handle_listener_exception(listener, event, e)
            raise

    def _handle_listener_exception(
        self, listener: LT, event: ET, exception: BaseException
    ):
        if self._exception_handlers:
            for handler in self._exception_handlers:
                handler(listener, event, exception)
        else:
            self.logger.exception(
                "exception in synced event listener '%s' for event '%s': %s",
                str(listener),
                str(event),
                str(exception),
            )


class BaseThreadedEventHandler(
    BaseSyncedEventHandler[LT, ET, FT], Generic[LT, ET, FT]
):
    """
    Runs each event listener in a separate thread and cancels it after the
    event_timeout.
    """

    __event_listener_type__ = SyncedEventListener

    event_type_name_prefix: str = ""
    logger = logging.getLogger("threaded_event_handler")

    _max_threads = 8

    def __init__(self, event_timeout: float = 10.0):
        super().__init__()

        self.event_timeout = event_timeout
        self._pool = cfutures.ThreadPoolExecutor(
            max_workers=self._max_threads,
            thread_name_prefix=f"{self._event_type_name_}_tasks",
        )

    def dispatch(self, event: ET, **kwargs) -> int:
        with cfutures.ThreadPoolExecutor(
            max_workers=self._max_threads,
            thread_name_prefix=f"{self._event_type_name_}_{event}_tasks",
        ) as pool:
            waiters_future = pool.submit(self._notify_waiters, event, **kwargs)

            listener_futures = []
            count = 0
            for listener in self.get_listeners(event):
                if event not in self._ignored_events:
                    listener_futures.append(pool.submit(
                        self._dispatch_listener,
                        event, listener, **kwargs
                    ))
                count += 1

            count += waiters_future.result(self.event_timeout)

            for listener_future in listener_futures:
                listener_future.result(self.event_timeout)

        if not count:
            self.logger.error(
                f"no listeners for {self._event_type_name} '%s'", event
            )

        return count

    @property
    def _event_type_name(self) -> str:
        if self.event_type_name_prefix:
            return " ".join((self.event_type_name_prefix, "event"))
        else:
            return "event"

    @property
    def _event_type_name_(self) -> str:
        return self._event_type_name.replace(" ", "_")

    def _dispatch_listener(self, event: ET, listener: LT, **kwargs):
        return listener(_event=event, **kwargs)


SyncedEventHandler = BaseSyncedEventHandler[
    SyncedEventListener[ET, FT, HT_co], ET, FT
]
SyncedEventHandler.__doc__ = BaseSyncedEventHandler.__doc__

ThreadedEventHandler = BaseThreadedEventHandler[
    SyncedEventListener[ET, FT, HT_co], ET, FT
]
ThreadedEventHandler.__doc__ = BaseThreadedEventHandler.__doc__
