# -*- coding: utf-8 -*-
# core/event_bus.py
"""
Event-system för kommunikation mellan plugins och app-kärna v2.1.0

Designprinciper:
    - Thread-safe för concurrent plugin-access
    - Async-support för moderna plugins
    - Request/Response via emit_collect för data-aggregering
    - Prioritetsbaserad exekvering
    - Schema-aware events för TS-integration
    - Structured logging istället för print()
    - Memory-safe med weak references där möjligt
    - Wildcard-prenumeration för namespace-events
    - Plugin-aware med automatisk cleanup
    - Decorator-support för clean plugin code
    - Middleware-chain för event transformation
    - Event transactions för atomära operationer

Standardiserade Event-namespaces:
    app:*           - Application lifecycle (app:ready, app:shutdown)
    plugin:*        - Plugin lifecycle (plugin:loaded, plugin:activated)
    vehicle:*       - Fordonshantering (vehicle:matched, vehicle:created)
    sap:*           - SAP-integration (sap:imported, sap:lookup)
    ts:*            - Transportstyrelsen (ts:file_generated, ts:response)
    ts:schema:*     - Schema-events (ts:schema:loaded, ts:schema:validated)
    ts:post:*       - Post-events (ts:post:pt28, ts:post:pt45, ts:post:pt99)
    ui:*            - UI-events (ui:refresh, ui:status_changed)
    data:*          - Data-events (data:changed, data:saved)
    error:*         - Felhantering (error:occurred, error:handled)

Ändringar v2.1.0:
    - logger -> _log (spec-konvention, module-level)
    - Kvarvarande f-string-loggning -> lazy %s-formatering
    - asyncio.get_event_loop() (deprecated i Python 3.12) fixad i
      _schedule_async_callback (get_running_loop + thread-pool-
      fallback) och wait_for_async (get_running_loop)
    - Oanvända importer borttagna (Generic, TypeVar T,
      EventEmitError)
    - AUTHOR + dynamisk copyright-helper

Ändringar v2.0.0:
    - Schema-aware events för TS-posttyper
    - Dynamisk event-registrering från scheman
    - Event middleware support
    - Event transactions
    - Förbättrad plugin-integration
    - Better async context handling
    - Event validation mot scheman
    - Event debouncing och throttling
    - Improved diagnostics och metrics

Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import fnmatch
import time
import uuid
from datetime import datetime
from enum import IntEnum
from dataclasses import dataclass, field
from typing import (
    Callable, Dict, List, Any, Optional, Union,
    Set, Tuple, Awaitable, TYPE_CHECKING,
    Protocol, runtime_checkable
)
from collections import defaultdict
from contextlib import contextmanager, asynccontextmanager
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, Future

from core.exceptions import (
    EventError,
    EventSubscriptionError
)

if TYPE_CHECKING:
    from core.plugin_base import PluginBase

_log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS & VERSION
# ══════════════════════════════════════════════════════════════════════════════

VERSION = "2.1.0"
AUTHOR = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# Type aliases
EventCallback = Callable[[Any], Any]
AsyncEventCallback = Callable[[Any], Awaitable[Any]]
AnyCallback = Union[EventCallback, AsyncEventCallback]
MiddlewareFunc = Callable[[str, Any, Callable], Any]


# ══════════════════════════════════════════════════════════════════════════════
# PRIORITY ENUM
# ══════════════════════════════════════════════════════════════════════════════

class Priority(IntEnum):
    """
    Exekveringsordning för subscribers.

    Lägre värde = körs tidigare.

    Användning:
        # Validering körs först
        bus.on("vehicle:save", validate_vehicle,
               priority=Priority.CRITICAL)

        # Schema-validering
        bus.on("ts:post:pt28", validate_schema,
               priority=Priority.SCHEMA)

        # Logging körs sist
        bus.on("vehicle:save", log_save, priority=Priority.MONITOR)
    """
    CRITICAL = 0      # Säkerhet, auth-checks, kan avbryta
    SCHEMA = 5        # Schema-validering
    HIGH = 10         # Data-transformation, enrichment
    NORMAL = 50       # Standard business logic
    LOW = 90          # Efterbearbetning, notifications
    MONITOR = 100     # Passiv observation, logging, metrics


# ══════════════════════════════════════════════════════════════════════════════
# PROTOCOLS
# ══════════════════════════════════════════════════════════════════════════════

@runtime_checkable
class SchemaProvider(Protocol):
    """Protocol för plugins som tillhandahåller scheman."""

    def get_schema(self, post_type: str) -> Optional[Dict[str, Any]]:
        """Hämta schema för en posttyp."""
        ...

    def get_all_schemas(self) -> Dict[str, Any]:
        """Hämta alla laddade scheman."""
        ...


@runtime_checkable
class EventMiddleware(Protocol):
    """Protocol för event middleware."""

    def process(
        self,
        event_name: str,
        data: Any,
        next_handler: Callable
    ) -> Any:
        """Processa event och anropa next_handler."""
        ...


# ══════════════════════════════════════════════════════════════════════════════
# EVENT DATA CLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class EventData:
    """
    Strukturerad event-data med metadata.

    Kan användas för att skicka mer information än bara payload.

    Exempel:
        event = EventData(
            payload={"vin": "WBA123..."},
            source="sap_import",
            cancellable=True,
            schema_type="PT28"  # Kopplad till TS-schema
        )
        bus.emit("vehicle:created", event)

        if event.cancelled:
            _log.info("Event was cancelled by a handler")
    """
    payload: Any = None
    source: str = ""
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(
        default_factory=lambda: str(uuid.uuid4())[:8]
    )

    # Cancellation support
    cancellable: bool = False
    cancelled: bool = False
    cancel_reason: str = ""

    # Schema integration
    schema_type: Optional[str] = None  # T.ex. "PT28", "PT45"
    schema_validated: bool = False
    validation_errors: List[str] = field(default_factory=list)

    # Transaction support
    transaction_id: Optional[str] = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Propagation control
    stop_propagation: bool = False

    def cancel(self, reason: str = "") -> None:
        """Avbryt eventet (om cancellable)."""
        if self.cancellable:
            self.cancelled = True
            self.cancel_reason = reason
            _log.debug(
                "Event %s cancelled: %s", self.event_id, reason,
            )
        else:
            raise EventError(
                "Cannot cancel non-cancellable event",
                error_code="EVENT_NOT_CANCELLABLE"
            )

    def stop(self) -> None:
        """Stoppa vidare propagering till andra handlers."""
        self.stop_propagation = True

    def add_validation_error(self, error: str) -> None:
        """Lägg till ett valideringsfel."""
        self.validation_errors.append(error)
        self.schema_validated = False

    def is_valid(self) -> bool:
        """Kontrollera om eventet är validerat utan fel."""
        return self.schema_validated and not self.validation_errors

    def __getitem__(self, key: str) -> Any:
        """Tillåt dict-liknande access till payload."""
        if isinstance(self.payload, dict):
            return self.payload[key]
        raise TypeError("Payload is not a dict")

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-liknande get med default."""
        if isinstance(self.payload, dict):
            return self.payload.get(key, default)
        return default

    def to_dict(self) -> Dict[str, Any]:
        """Konvertera till dict för serialisering."""
        return {
            "event_id": self.event_id,
            "payload": self.payload,
            "source": self.source,
            "timestamp": self.timestamp,
            "schema_type": self.schema_type,
            "schema_validated": self.schema_validated,
            "validation_errors": self.validation_errors,
            "cancelled": self.cancelled,
            "metadata": self.metadata
        }


@dataclass
class Subscriber:
    """En registrerad event-lyssnare."""
    callback: AnyCallback
    priority: int = Priority.NORMAL
    once: bool = False
    source: str = ""  # Plugin-namn för diagnostik
    is_async: bool = False
    filter_func: Optional[Callable[[Any], bool]] = None
    schema_type: Optional[str] = None  # Filtrera på schema-typ
    debounce_ms: int = 0  # Debounce i millisekunder
    throttle_ms: int = 0  # Throttle i millisekunder

    # Internal state
    _last_call: float = field(default=0.0, repr=False)
    _debounce_timer: Optional[threading.Timer] = field(
        default=None, repr=False
    )

    def __post_init__(self):
        """Detektera om callback är async."""
        self.is_async = asyncio.iscoroutinefunction(self.callback)

    def __hash__(self):
        return id(self.callback)

    def __eq__(self, other):
        if isinstance(other, Subscriber):
            return self.callback is other.callback
        return NotImplemented

    def matches_filter(self, data: Any) -> bool:
        """Kontrollera om data matchar filtret."""
        # Schema-filter
        if self.schema_type is not None:
            if (
                isinstance(data, EventData)
                and data.schema_type != self.schema_type
            ):
                return False

        # Custom filter
        if self.filter_func is None:
            return True
        try:
            return self.filter_func(data)
        except Exception:
            return True  # Vid fel, kör ändå

    def should_invoke(self) -> bool:
        """Kontrollera throttle/debounce."""
        now = time.time() * 1000  # ms

        if self.throttle_ms > 0:
            if now - self._last_call < self.throttle_ms:
                return False

        self._last_call = now
        return True

    def cancel_debounce(self) -> None:
        """Avbryt väntande debounce."""
        if self._debounce_timer:
            self._debounce_timer.cancel()
            self._debounce_timer = None


@dataclass
class EventStats:
    """Statistik för ett specifikt event."""
    emit_count: int = 0
    total_time_ms: float = 0.0
    error_count: int = 0
    cancelled_count: int = 0
    last_emit: Optional[float] = None
    avg_subscribers: float = 0.0
    schema_validation_failures: int = 0

    @property
    def avg_time_ms(self) -> float:
        """Genomsnittlig tid per emit."""
        if self.emit_count == 0:
            return 0.0
        return self.total_time_ms / self.emit_count

    @property
    def error_rate(self) -> float:
        """Felfrekvens."""
        if self.emit_count == 0:
            return 0.0
        return self.error_count / self.emit_count


@dataclass
class EventTransaction:
    """
    Grupperar relaterade events för atomär hantering.

    Användning:
        with bus.transaction("batch_import") as tx:
            for vehicle in vehicles:
                bus.emit("vehicle:created", vehicle, transaction=tx)
            # Alla events committas här
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    events: List[Tuple[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    committed: bool = False
    rolled_back: bool = False

    def add_event(self, event_name: str, data: Any) -> None:
        """Lägg till event i transaktionen."""
        if isinstance(data, EventData):
            data.transaction_id = self.id
        self.events.append((event_name, data))

    def commit(self) -> None:
        """Markera som committad."""
        self.committed = True

    def rollback(self) -> None:
        """Markera som rollbackad."""
        self.rolled_back = True
        self.events.clear()


# ══════════════════════════════════════════════════════════════════════════════
# DECORATORS
# ══════════════════════════════════════════════════════════════════════════════

def on_event(
    event_name: str,
    priority: int = Priority.NORMAL,
    once: bool = False,
    schema_type: Optional[str] = None,
    debounce_ms: int = 0,
    throttle_ms: int = 0
):
    """
    Decorator för att markera en metod som event-handler.

    Används med EventBus.register_plugin_handlers för automatisk
    registrering.
    """
    def decorator(func: AnyCallback) -> AnyCallback:
        if not hasattr(func, '_event_subscriptions'):
            func._event_subscriptions = []

        func._event_subscriptions.append({
            'event_name': event_name,
            'priority': priority,
            'once': once,
            'schema_type': schema_type,
            'debounce_ms': debounce_ms,
            'throttle_ms': throttle_ms
        })

        return func
    return decorator


def schema_event(post_type: str, priority: int = Priority.SCHEMA):
    """
    Decorator för schema-relaterade event handlers.
    """
    def decorator(func: AnyCallback) -> AnyCallback:
        return on_event(
            f"ts:post:{post_type.lower()}",
            priority=priority,
            schema_type=post_type
        )(func)
    return decorator


def cancellable_event(func: Callable) -> Callable:
    """
    Decorator som gör att event-emittering stödjer cancellation.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    wrapper._is_cancellable = True
    return wrapper


# ══════════════════════════════════════════════════════════════════════════════
# MIDDLEWARE
# ══════════════════════════════════════════════════════════════════════════════

class SchemaValidationMiddleware:
    """
    Middleware som validerar events mot TS-scheman.

    Integrerar med ts_spec_import plugin.
    """

    def __init__(
        self, schema_provider: Optional[SchemaProvider] = None
    ):
        self.schema_provider = schema_provider
        self._schema_cache: Dict[str, Any] = {}

    def set_schema_provider(self, provider: SchemaProvider) -> None:
        """Sätt schema-provider (kallas av ts_spec_import)."""
        self.schema_provider = provider
        self._schema_cache.clear()
        _log.debug("Schema provider updated in middleware")

    def process(
        self,
        event_name: str,
        data: Any,
        next_handler: Callable
    ) -> Any:
        """Validera event-data mot schema om tillämpligt."""
        # Kolla om detta är ett schema-relaterat event
        if not event_name.startswith("ts:post:"):
            return next_handler(event_name, data)

        # Extrahera posttyp från event-namn
        post_type = event_name.split(":")[-1].upper()  # "pt28" -> "PT28"

        if isinstance(data, EventData):
            data.schema_type = post_type

            # Validera om vi har schema-provider
            if self.schema_provider:
                schema = self._get_schema(post_type)
                if schema:
                    errors = self._validate_against_schema(
                        data.payload, schema
                    )
                    if errors:
                        for error in errors:
                            data.add_validation_error(error)
                        _log.warning(
                            "Schema validation failed for %s: %s",
                            post_type, errors,
                        )
                    else:
                        data.schema_validated = True

        return next_handler(event_name, data)

    def _get_schema(self, post_type: str) -> Optional[Dict[str, Any]]:
        """Hämta schema med caching."""
        if post_type not in self._schema_cache:
            if self.schema_provider:
                self._schema_cache[post_type] = (
                    self.schema_provider.get_schema(post_type)
                )
        return self._schema_cache.get(post_type)

    def _validate_against_schema(
        self,
        data: Any,
        schema: Dict[str, Any]
    ) -> List[str]:
        """Validera data mot schema."""
        errors = []

        if not isinstance(data, dict):
            return errors

        # Validera fält baserat på schema
        fields = schema.get("fields", {})

        for field_name, field_spec in fields.items():
            if field_spec.get("required", False):
                if field_name not in data or data[field_name] is None:
                    errors.append(
                        f"Required field missing: {field_name}"
                    )

            if field_name in data and data[field_name] is not None:
                value = data[field_name]

                # Längdvalidering
                max_length = field_spec.get("length")
                if max_length and len(str(value)) > max_length:
                    errors.append(
                        f"Field '{field_name}' exceeds max length "
                        f"{max_length}"
                    )

                # Typvalidering
                field_type = field_spec.get("type", "AN")
                if field_type == "N" and not str(value).isdigit():
                    errors.append(
                        f"Field '{field_name}' must be numeric"
                    )

        return errors


class LoggingMiddleware:
    """Middleware för event-logging."""

    def __init__(self, log_level: int = logging.DEBUG):
        self.log_level = log_level

    def process(
        self,
        event_name: str,
        data: Any,
        next_handler: Callable
    ) -> Any:
        """Logga event före och efter hantering."""
        start = time.perf_counter()

        _log.log(self.log_level, "Event START: %s", event_name)

        try:
            result = next_handler(event_name, data)
            elapsed = (time.perf_counter() - start) * 1000

            _log.log(
                self.log_level,
                "Event END: %s (%.2fms)", event_name, elapsed,
            )

            return result
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            _log.error(
                "Event FAILED: %s (%.2fms) - %s",
                event_name, elapsed, e,
            )
            raise


# ══════════════════════════════════════════════════════════════════════════════
# EVENT BUS
# ══════════════════════════════════════════════════════════════════════════════

class EventBus:
    """
    Thread-safe Pub/Sub event-system med prioritering,
    schema-support och diagnostik.
    """

    def __init__(
        self,
        collect_stats: bool = True,
        enable_schema_validation: bool = True
    ):
        """
        Initiera EventBus.

        Args:
            collect_stats: Samla statistik för events (liten overhead)
            enable_schema_validation: Aktivera schema-validering
        """
        self._lock = threading.RLock()
        self._subscribers: Dict[str, List[Subscriber]] = (
            defaultdict(list)
        )
        self._plugin_subscriptions: Dict[
            str, Set[Tuple[str, Callable]]
        ] = defaultdict(set)
        # (timestamp, event, source)
        self._event_history: List[Tuple[float, str, str]] = []
        self._history_limit = 1000
        self._muted_events: Set[str] = set()
        self._emit_depth = 0
        self._max_emit_depth = 10

        # Middleware chain
        self._middlewares: List[Any] = []
        self._enable_schema_validation = enable_schema_validation

        if enable_schema_validation:
            self._schema_middleware = SchemaValidationMiddleware()
            self._middlewares.append(self._schema_middleware)
        else:
            self._schema_middleware = None

        # Statistik
        self._collect_stats = collect_stats
        self._stats: Dict[str, EventStats] = defaultdict(EventStats)

        # Pending async tasks
        self._pending_tasks: Set[asyncio.Task] = set()

        # Replay buffer för late subscribers
        self._replay_buffer: Dict[str, List[Tuple[float, Any]]] = (
            defaultdict(list)
        )
        self._replay_events: Set[str] = set()
        self._replay_limit = 100

        # Transaction support
        self._active_transactions: Dict[str, EventTransaction] = {}

        # Thread pool för async callbacks
        self._thread_pool = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="eventbus"
        )

        # Schema registry
        self._schema_events: Set[str] = set()

        _log.debug("EventBus v%s initialized", VERSION)

    # ─── Schema Integration ────────────────────────────────────────────────────

    def set_schema_provider(self, provider: SchemaProvider) -> None:
        """
        Sätt schema-provider för validering.
        """
        if self._schema_middleware:
            self._schema_middleware.set_schema_provider(provider)
            _log.info("Schema provider registered with EventBus")

    def register_schema_events(self, post_types: List[str]) -> None:
        """
        Registrera schema-events för posttyper.
        """
        with self._lock:
            for post_type in post_types:
                event_name = f"ts:post:{post_type.lower()}"
                self._schema_events.add(event_name)
                _log.debug(
                    "Registered schema event: %s", event_name,
                )

        self.emit("ts:schema:events_registered", {
            "post_types": post_types,
            "events": list(self._schema_events)
        })

    def get_schema_events(self) -> Set[str]:
        """Returnera alla registrerade schema-events."""
        with self._lock:
            return self._schema_events.copy()

    # ─── Middleware ────────────────────────────────────────────────────────────

    def add_middleware(self, middleware: Any) -> None:
        """
        Lägg till middleware i chain.
        """
        if not hasattr(middleware, 'process') or not callable(
            middleware.process
        ):
            raise EventError(
                "Middleware must have a 'process' method",
                error_code="INVALID_MIDDLEWARE"
            )

        with self._lock:
            self._middlewares.append(middleware)
            _log.debug(
                "Added middleware: %s", type(middleware).__name__,
            )

    def remove_middleware(self, middleware: Any) -> bool:
        """Ta bort middleware från chain."""
        with self._lock:
            try:
                self._middlewares.remove(middleware)
                return True
            except ValueError:
                return False

    def _run_middleware_chain(
        self,
        event_name: str,
        data: Any
    ) -> Tuple[str, Any]:
        """Kör event genom middleware-chain."""
        if not self._middlewares:
            return event_name, data

        def create_next(index: int) -> Callable:
            if index >= len(self._middlewares):
                return lambda e, d: (e, d)

            middleware = self._middlewares[index]
            next_handler = create_next(index + 1)

            def handler(e: str, d: Any):
                return middleware.process(e, d, next_handler)

            return handler

        chain = create_next(0)
        result = chain(event_name, data)

        # Hantera olika return-typer
        if isinstance(result, tuple) and len(result) == 2:
            return result
        else:
            return event_name, data

    # ─── Registrering ──────────────────────────────────────────────────────────

    def on(
        self,
        event_name: str,
        callback: AnyCallback,
        priority: int = Priority.NORMAL,
        source: str = "",
        filter_func: Optional[Callable[[Any], bool]] = None,
        schema_type: Optional[str] = None,
        debounce_ms: int = 0,
        throttle_ms: int = 0
    ) -> AnyCallback:
        """
        Prenumerera på ett event.
        """
        if not callable(callback):
            raise EventSubscriptionError(
                "Callback must be callable",
                event_name=event_name
            )

        sub = Subscriber(
            callback=callback,
            priority=priority,
            source=source,
            filter_func=filter_func,
            schema_type=schema_type,
            debounce_ms=debounce_ms,
            throttle_ms=throttle_ms
        )

        with self._lock:
            subscribers = self._subscribers[event_name]

            # Undvik dubbelregistrering
            for existing in subscribers:
                if existing.callback is callback:
                    _log.warning(
                        "Duplicate subscriber ignored: %s [%s]",
                        event_name, source or "anonymous"
                    )
                    return callback

            subscribers.append(sub)
            subscribers.sort(key=lambda s: s.priority)

            # Spåra plugin-subscriptions för cleanup
            if source:
                self._plugin_subscriptions[source].add(
                    (event_name, callback)
                )

        _log.debug(
            "Subscriber registered: %s [%s] prio=%d async=%s schema=%s",
            event_name, source or "anonymous", priority,
            sub.is_async, schema_type
        )

        # Replay buffrade events om tillämpligt
        if event_name in self._replay_events:
            self._replay_to_subscriber(event_name, sub)

        return callback

    def once(
        self,
        event_name: str,
        callback: AnyCallback,
        priority: int = Priority.NORMAL,
        source: str = ""
    ) -> AnyCallback:
        """
        Prenumerera på ett event en enda gång.
        """
        sub = Subscriber(
            callback=callback,
            priority=priority,
            once=True,
            source=source
        )

        with self._lock:
            self._subscribers[event_name].append(sub)
            self._subscribers[event_name].sort(
                key=lambda s: s.priority
            )

            if source:
                self._plugin_subscriptions[source].add(
                    (event_name, callback)
                )

        _log.debug(
            "Once subscriber registered: %s [%s]",
            event_name, source or "anonymous"
        )

        return callback

    def off(
        self,
        event_name: str,
        callback: Optional[AnyCallback] = None
    ) -> int:
        """
        Avsluta prenumeration.
        """
        removed = 0

        with self._lock:
            if event_name not in self._subscribers:
                return 0

            if callback is None:
                # Ta bort alla för detta event
                removed = len(self._subscribers[event_name])

                # Avbryt debounce-timers
                for sub in self._subscribers[event_name]:
                    sub.cancel_debounce()
                    if sub.source:
                        self._plugin_subscriptions[sub.source].discard(
                            (event_name, sub.callback)
                        )

                del self._subscribers[event_name]
            else:
                # Ta bort specifik callback
                before = len(self._subscribers[event_name])
                to_remove = [
                    s for s in self._subscribers[event_name]
                    if s.callback is callback
                ]

                for sub in to_remove:
                    sub.cancel_debounce()

                self._subscribers[event_name] = [
                    s for s in self._subscribers[event_name]
                    if s.callback is not callback
                ]
                removed = before - len(self._subscribers[event_name])

                # Uppdatera plugin-tracking
                for source, subs in self._plugin_subscriptions.items():
                    subs.discard((event_name, callback))

        if removed:
            _log.debug(
                "Removed %d subscriber(s) from '%s'",
                removed, event_name
            )

        return removed

    def off_all(self, source: str) -> int:
        """
        Avregistrera ALLA prenumerationer från en plugin.
        """
        removed = 0

        with self._lock:
            subscriptions = self._plugin_subscriptions.get(
                source, set()
            ).copy()

            for event_name, callback in subscriptions:
                if event_name in self._subscribers:
                    before = len(self._subscribers[event_name])

                    # Avbryt debounce och ta bort
                    for sub in self._subscribers[event_name]:
                        if sub.callback is callback:
                            sub.cancel_debounce()

                    self._subscribers[event_name] = [
                        s for s in self._subscribers[event_name]
                        if s.callback is not callback
                    ]
                    removed += before - len(
                        self._subscribers[event_name]
                    )

            self._plugin_subscriptions.pop(source, None)

        if removed:
            _log.info(
                "Removed %d subscriber(s) for plugin '%s'",
                removed, source
            )

        return removed

    def register_plugin_handlers(self, plugin: PluginBase) -> int:
        """
        Registrera alla @on_event-dekorerade metoder från en plugin.
        """
        plugin_name = getattr(
            plugin, 'name', plugin.__class__.__name__
        )
        registered = 0

        for attr_name in dir(plugin):
            if attr_name.startswith('_'):
                continue

            try:
                attr = getattr(plugin, attr_name)
            except Exception:
                continue

            if callable(attr) and hasattr(attr, '_event_subscriptions'):
                for sub_info in attr._event_subscriptions:
                    self.on(
                        event_name=sub_info['event_name'],
                        callback=attr,
                        priority=sub_info['priority'],
                        source=plugin_name,
                        schema_type=sub_info.get('schema_type'),
                        debounce_ms=sub_info.get('debounce_ms', 0),
                        throttle_ms=sub_info.get('throttle_ms', 0)
                    )

                    if sub_info['once']:
                        with self._lock:
                            for s in self._subscribers[
                                sub_info['event_name']
                            ]:
                                if s.callback is attr:
                                    s.once = True
                                    break

                    registered += 1

        if registered:
            _log.debug(
                "Registered %d event handlers for plugin '%s'",
                registered, plugin_name
            )

        return registered

    # ─── Emittering ────────────────────────────────────────────────────────────

    def emit(
        self,
        event_name: str,
        data: Any = None,
        *,
        source: str = "",
        transaction: Optional[EventTransaction] = None
    ) -> int:
        """
        Emittera ett event till alla matchande subscribers.
        """
        if event_name in self._muted_events:
            return 0

        # Lägg till i transaction om aktiv
        if transaction is not None:
            transaction.add_event(event_name, data)
            if not transaction.committed:
                return 0  # Vänta på commit

        self._emit_depth += 1
        if self._emit_depth > self._max_emit_depth:
            self._emit_depth -= 1
            error_msg = (
                f"Max emit depth ({self._max_emit_depth}) exceeded "
                f"for '{event_name}' — trolig infinite loop"
            )
            _log.error("%s", error_msg)
            raise RecursionError(error_msg)

        start_time = time.perf_counter()

        try:
            # Sortera genom middleware-chain
            processed_name, processed_data = (
                self._run_middleware_chain(event_name, data)
            )

            count = self._do_emit(
                processed_name, processed_data, source
            )

            # Uppdatera statistik
            if self._collect_stats:
                elapsed = (time.perf_counter() - start_time) * 1000
                self._update_stats(event_name, elapsed, error=False)

            return count

        except Exception:
            if self._collect_stats:
                elapsed = (time.perf_counter() - start_time) * 1000
                self._update_stats(event_name, elapsed, error=True)
            raise

        finally:
            self._emit_depth -= 1

    def _do_emit(
        self, event_name: str, data: Any, source: str = ""
    ) -> int:
        """Intern emit-logik med wildcard-matching."""
        matched: List[Subscriber] = []

        with self._lock:
            # Exakta matchningar
            if event_name in self._subscribers:
                matched.extend(self._subscribers[event_name])

            # Wildcard-matchningar
            for pattern, subs in self._subscribers.items():
                if pattern != event_name and '*' in pattern:
                    if fnmatch.fnmatch(event_name, pattern):
                        matched.extend(subs)

            # Sortera efter prioritet
            matched.sort(key=lambda s: s.priority)

            # Logga i historik
            self._record_event(event_name, source)

            # Buffra för replay om aktiverat
            if event_name in self._replay_events:
                self._add_to_replay_buffer(event_name, data)

        # Exekvera utanför lock
        invoked = 0
        once_to_remove: List[Tuple[str, Subscriber]] = []
        is_event_data = isinstance(data, EventData)

        for sub in matched:
            # Kontrollera filter
            if not sub.matches_filter(data):
                continue

            # Kontrollera throttle
            if not sub.should_invoke():
                continue

            # Kontrollera cancellation
            if is_event_data and data.cancelled:
                _log.debug(
                    "Event '%s' cancelled, skipping remaining "
                    "handlers",
                    event_name
                )
                if self._collect_stats:
                    self._stats[event_name].cancelled_count += 1
                break

            # Kontrollera stop propagation
            if is_event_data and data.stop_propagation:
                break

            try:
                # Debounce support
                if sub.debounce_ms > 0:
                    self._schedule_debounced(sub, data, event_name)
                elif sub.is_async:
                    self._schedule_async_callback(
                        sub.callback, data, event_name, sub.source
                    )
                else:
                    sub.callback(data)

                invoked += 1

                if sub.once:
                    once_to_remove.append((event_name, sub))

            except Exception as e:
                _log.exception(
                    "Event callback failed: %s [%s] - %s",
                    event_name,
                    sub.source or sub.callback.__name__,
                    str(e)
                )

        # Rensa once-subscribers
        if once_to_remove:
            with self._lock:
                for evt, sub in once_to_remove:
                    try:
                        self._subscribers[evt].remove(sub)
                        if sub.source:
                            self._plugin_subscriptions[
                                sub.source
                            ].discard((evt, sub.callback))
                    except ValueError:
                        pass

        return invoked

    def _schedule_debounced(
        self,
        sub: Subscriber,
        data: Any,
        event_name: str
    ) -> None:
        """Schemalägg debounced callback."""
        sub.cancel_debounce()

        def execute():
            try:
                if sub.is_async:
                    self._schedule_async_callback(
                        sub.callback, data, event_name, sub.source
                    )
                else:
                    sub.callback(data)
            except Exception:
                _log.exception(
                    "Debounced callback failed: %s [%s]",
                    event_name, sub.source
                )

        sub._debounce_timer = threading.Timer(
            sub.debounce_ms / 1000,
            execute
        )
        sub._debounce_timer.start()

    def emit_collect(
        self,
        event_name: str,
        data: Any = None,
        *,
        filter_none: bool = False,
        timeout: Optional[float] = None
    ) -> List[Any]:
        """
        Emittera och samla returvärden från alla subscribers.
        """
        if event_name in self._muted_events:
            return []

        # Kör genom middleware
        processed_name, processed_data = self._run_middleware_chain(
            event_name, data
        )

        results: List[Any] = []
        async_futures: List[Future] = []

        with self._lock:
            matched = list(
                self._subscribers.get(processed_name, [])
            )

            # Wildcard-matchningar
            for pattern, subs in self._subscribers.items():
                if pattern != processed_name and '*' in pattern:
                    if fnmatch.fnmatch(processed_name, pattern):
                        matched.extend(subs)

            matched.sort(key=lambda s: s.priority)
            self._record_event(processed_name, "emit_collect")

        once_to_remove: List[Subscriber] = []

        for sub in matched:
            if not sub.matches_filter(processed_data):
                continue

            try:
                if sub.is_async:
                    future = self._thread_pool.submit(
                        self._run_async_callback,
                        sub.callback,
                        processed_data,
                        timeout
                    )
                    async_futures.append(future)
                else:
                    result = sub.callback(processed_data)
                    results.append(result)

                if sub.once:
                    once_to_remove.append(sub)

            except Exception:
                _log.exception(
                    "Event collect callback failed: %s [%s]",
                    processed_name,
                    sub.source or sub.callback.__name__
                )
                results.append(None)

        # Svara på alla async results
        for future in async_futures:
            try:
                result = future.result(timeout=timeout)
                results.append(result)
            except TimeoutError:
                _log.warning(
                    "Async handler timeout for '%s'",
                    processed_name
                )
                results.append(None)
            except Exception:
                _log.exception(
                    "Async handler failed for '%s'",
                    processed_name
                )
                results.append(None)

        # Rensa once-subscribers
        if once_to_remove:
            with self._lock:
                for sub in once_to_remove:
                    try:
                        self._subscribers[processed_name].remove(sub)
                    except ValueError:
                        pass

        if filter_none:
            results = [r for r in results if r is not None]

        return results

    def _run_async_callback(
        self,
        callback: AsyncEventCallback,
        data: Any,
        timeout: Optional[float]
    ) -> Any:
        """Kör async callback i thread pool."""
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(
                asyncio.wait_for(callback(data), timeout)
            )
        finally:
            loop.close()

    async def emit_async(
        self,
        event_name: str,
        data: Any = None,
        *,
        source: str = ""
    ) -> int:
        """
        Async version av emit - väntar på alla async handlers.
        """
        if event_name in self._muted_events:
            return 0

        # Kör genom middleware
        processed_name, processed_data = self._run_middleware_chain(
            event_name, data
        )

        matched: List[Subscriber] = []

        with self._lock:
            if processed_name in self._subscribers:
                matched.extend(self._subscribers[processed_name])

            for pattern, subs in self._subscribers.items():
                if pattern != processed_name and '*' in pattern:
                    if fnmatch.fnmatch(processed_name, pattern):
                        matched.extend(subs)

            matched.sort(key=lambda s: s.priority)
            self._record_event(processed_name, source)

        invoked = 0
        once_to_remove: List[Tuple[str, Subscriber]] = []
        is_event_data = isinstance(processed_data, EventData)

        for sub in matched:
            if not sub.matches_filter(processed_data):
                continue

            if is_event_data and (
                processed_data.cancelled
                or processed_data.stop_propagation
            ):
                break

            try:
                if sub.is_async:
                    await sub.callback(processed_data)
                else:
                    sub.callback(processed_data)

                invoked += 1

                if sub.once:
                    once_to_remove.append((processed_name, sub))

            except Exception:
                _log.exception(
                    "Async event callback failed: %s [%s]",
                    processed_name,
                    sub.source or sub.callback.__name__
                )

        if once_to_remove:
            with self._lock:
                for evt, sub in once_to_remove:
                    try:
                        self._subscribers[evt].remove(sub)
                    except ValueError:
                        pass

        return invoked

    # ─── Transaction Support ───────────────────────────────────────────────────

    @contextmanager
    def transaction(self, name: str = ""):
        """
        Gruppera events i en transaction.

        Events emitteras först vid commit (context exit).
        """
        tx = EventTransaction()
        tx.id = f"{name}_{tx.id}" if name else tx.id

        self._active_transactions[tx.id] = tx

        try:
            yield tx
            tx.commit()

            # Emittera alla buffrade events
            for event_name, data in tx.events:
                self.emit(event_name, data)

        except Exception:
            tx.rollback()
            raise

        finally:
            self._active_transactions.pop(tx.id, None)

    @asynccontextmanager
    async def transaction_async(self, name: str = ""):
        """Async version av transaction."""
        tx = EventTransaction()
        tx.id = f"{name}_{tx.id}" if name else tx.id

        self._active_transactions[tx.id] = tx

        try:
            yield tx
            tx.commit()

            for event_name, data in tx.events:
                await self.emit_async(event_name, data)

        except Exception:
            tx.rollback()
            raise

        finally:
            self._active_transactions.pop(tx.id, None)

    # ─── Replay Support ────────────────────────────────────────────────────────

    def enable_replay(
        self, event_name: str, buffer_size: int = 100
    ) -> None:
        """
        Aktivera replay för ett event.
        """
        with self._lock:
            self._replay_events.add(event_name)
            self._replay_limit = buffer_size

    def disable_replay(self, event_name: str) -> None:
        """Inaktivera replay och rensa buffer."""
        with self._lock:
            self._replay_events.discard(event_name)
            self._replay_buffer.pop(event_name, None)

    def _add_to_replay_buffer(
        self, event_name: str, data: Any
    ) -> None:
        """Lägg till i replay-buffer (anropas under lock)."""
        buffer = self._replay_buffer[event_name]
        buffer.append((time.time(), data))

        if len(buffer) > self._replay_limit:
            self._replay_buffer[event_name] = (
                buffer[-self._replay_limit:]
            )

    def _replay_to_subscriber(
        self, event_name: str, subscriber: Subscriber
    ) -> None:
        """Skicka buffrade events till ny subscriber."""
        with self._lock:
            buffer = self._replay_buffer.get(event_name, [])

        for timestamp, data in buffer:
            if not subscriber.matches_filter(data):
                continue

            try:
                if subscriber.is_async:
                    self._schedule_async_callback(
                        subscriber.callback, data,
                        event_name, subscriber.source
                    )
                else:
                    subscriber.callback(data)
            except Exception:
                _log.exception(
                    "Replay callback failed: %s [%s]",
                    event_name,
                    subscriber.source
                )

    # ─── Kontrollverktyg ───────────────────────────────────────────────────────

    @contextmanager
    def muted(self, *event_names: str):
        """
        Tillfälligt tysta specifika events.
        """
        with self._lock:
            self._muted_events.update(event_names)
        try:
            yield
        finally:
            with self._lock:
                self._muted_events -= set(event_names)

    @contextmanager
    def batch_mode(self, *events_to_consolidate: str):
        """
        Batch-läge där events samlas och emitteras en gång i slutet.
        """
        batched: Dict[str, List[Any]] = defaultdict(list)
        original_emit = self.emit

        def batched_emit(event_name: str, data: Any = None, **kwargs):
            if event_name in events_to_consolidate:
                batched[event_name].append(data)
                return 0
            return original_emit(event_name, data, **kwargs)

        self.emit = batched_emit
        try:
            yield
        finally:
            self.emit = original_emit

            for event_name, data_list in batched.items():
                if data_list:
                    if len(data_list) == 1:
                        self.emit(event_name, data_list[0])
                    else:
                        self.emit(event_name, {
                            'batch': True,
                            'items': data_list,
                            'count': len(data_list)
                        })

    def wait_for(
        self,
        event_name: str,
        timeout: Optional[float] = None,
        predicate: Optional[Callable[[Any], bool]] = None
    ) -> Optional[Any]:
        """
        Blockera tills ett event emitteras.
        """
        event = threading.Event()
        result_holder = [None]

        def handler(data):
            if predicate is None or predicate(data):
                result_holder[0] = data
                event.set()

        self.once(event_name, handler)

        if event.wait(timeout):
            return result_holder[0]
        else:
            self.off(event_name, handler)
            return None

    async def wait_for_async(
        self,
        event_name: str,
        timeout: Optional[float] = None,
        predicate: Optional[Callable[[Any], bool]] = None
    ) -> Optional[Any]:
        """
        Async version av wait_for.

        FIXAT v2.1.0: asyncio.get_event_loop() (deprecated) ->
        asyncio.get_running_loop().
        """
        future: asyncio.Future = (
            asyncio.get_running_loop().create_future()
        )

        def handler(data):
            if predicate is None or predicate(data):
                if not future.done():
                    future.get_loop().call_soon_threadsafe(
                        future.set_result, data
                    )

        self.once(event_name, handler)

        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            self.off(event_name, handler)
            return None

    # ─── Diagnostik ────────────────────────────────────────────────────────────

    def get_subscribers(self, event_name: str) -> List[Dict[str, Any]]:
        """
        Lista subscribers med metadata för diagnostik.
        """
        with self._lock:
            return [
                {
                    "callback": s.callback.__name__,
                    "priority": s.priority,
                    "priority_name": (
                        Priority(s.priority).name
                        if s.priority in [p.value for p in Priority]
                        else "CUSTOM"
                    ),
                    "source": s.source,
                    "once": s.once,
                    "is_async": s.is_async,
                    "has_filter": s.filter_func is not None,
                    "schema_type": s.schema_type,
                    "debounce_ms": s.debounce_ms,
                    "throttle_ms": s.throttle_ms,
                }
                for s in self._subscribers.get(event_name, [])
            ]

    def get_all_events(self) -> Dict[str, int]:
        """Returnera alla registrerade events och antal subscribers."""
        with self._lock:
            return {
                name: len(subs)
                for name, subs in self._subscribers.items()
                if subs
            }

    def get_plugin_events(self, plugin_name: str) -> List[str]:
        """Lista alla events som en plugin prenumererar på."""
        with self._lock:
            subs = self._plugin_subscriptions.get(plugin_name, set())
            return list(set(event for event, _ in subs))

    def get_recent_events(
        self, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Returnera senaste emitterade events med timestamps.
        """
        with self._lock:
            return [
                {"timestamp": ts, "event": name, "source": src}
                for ts, name, src in self._event_history[-limit:]
            ]

    def get_stats(
        self, event_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Hämta statistik för events.
        """
        if not self._collect_stats:
            return {"error": "Stats collection disabled"}

        with self._lock:
            if event_name:
                stats = self._stats.get(event_name, EventStats())
                return {
                    "event": event_name,
                    "emit_count": stats.emit_count,
                    "total_time_ms": round(stats.total_time_ms, 2),
                    "avg_time_ms": round(stats.avg_time_ms, 2),
                    "error_count": stats.error_count,
                    "error_rate": round(stats.error_rate * 100, 1),
                    "cancelled_count": stats.cancelled_count,
                    "schema_validation_failures": (
                        stats.schema_validation_failures
                    ),
                    "last_emit": stats.last_emit,
                    "subscriber_count": len(
                        self._subscribers.get(event_name, [])
                    )
                }
            else:
                return {
                    name: {
                        "emit_count": s.emit_count,
                        "avg_time_ms": round(s.avg_time_ms, 2),
                        "error_count": s.error_count,
                        "error_rate": round(s.error_rate * 100, 1)
                    }
                    for name, s in self._stats.items()
                    if s.emit_count > 0
                }

    def subscriber_count(self, event_name: str) -> int:
        """Antal aktiva subscribers för ett event."""
        with self._lock:
            return len(self._subscribers.get(event_name, []))

    def clear_all(self) -> None:
        """
        Rensa ALLA subscribers.
        """
        with self._lock:
            # Avbryt alla debounce-timers
            for subs in self._subscribers.values():
                for sub in subs:
                    sub.cancel_debounce()

            self._subscribers.clear()
            self._plugin_subscriptions.clear()
            self._event_history.clear()
            self._muted_events.clear()
            self._stats.clear()
            self._replay_buffer.clear()
            self._replay_events.clear()
            self._schema_events.clear()
            self._active_transactions.clear()

        _log.info("EventBus cleared — all subscribers removed")

    def reset_stats(self) -> None:
        """Nollställ all statistik."""
        with self._lock:
            self._stats.clear()

    def shutdown(self) -> None:
        """Graceful shutdown."""
        self.clear_all()
        self._thread_pool.shutdown(wait=True)
        _log.info("EventBus shutdown complete")

    # ─── Internals ─────────────────────────────────────────────────────────────

    def _record_event(self, event_name: str, source: str = "") -> None:
        """Logga event i historik (anropas under lock)."""
        self._event_history.append(
            (time.time(), event_name, source)
        )
        if len(self._event_history) > self._history_limit:
            self._event_history = (
                self._event_history[-self._history_limit:]
            )

    def _update_stats(
        self, event_name: str, elapsed_ms: float, error: bool
    ) -> None:
        """Uppdatera statistik för ett event."""
        with self._lock:
            stats = self._stats[event_name]
            stats.emit_count += 1
            stats.total_time_ms += elapsed_ms
            stats.last_emit = time.time()

            if error:
                stats.error_count += 1

            sub_count = len(self._subscribers.get(event_name, []))
            stats.avg_subscribers = (
                (
                    stats.avg_subscribers * (stats.emit_count - 1)
                    + sub_count
                )
                / stats.emit_count
            )

    def _schedule_async_callback(
        self,
        callback: AsyncEventCallback,
        data: Any,
        event_name: str,
        source: str
    ) -> None:
        """
        Schemalägg async callback för körning.

        FIXAT v2.1.0: asyncio.get_event_loop() (deprecated i 3.12)
        ersatt: körande loop -> ensure_future, annars thread pool.
        """
        async def wrapped():
            try:
                await callback(data)
            except Exception:
                _log.exception(
                    "Async event callback failed: %s [%s]",
                    event_name, source
                )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            task = asyncio.ensure_future(wrapped())
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
        else:
            # Ingen körande loop — kör i thread pool med egen loop
            self._thread_pool.submit(
                self._run_async_callback,
                callback,
                data,
                None
            )

    def __repr__(self) -> str:
        with self._lock:
            total_subs = sum(
                len(s) for s in self._subscribers.values()
            )
            event_count = len(self._subscribers)
            plugin_count = len(self._plugin_subscriptions)
            schema_count = len(self._schema_events)

        return (
            f"<EventBus v{VERSION} "
            f"events={event_count} "
            f"subscribers={total_subs} "
            f"plugins={plugin_count} "
            f"schemas={schema_count}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
# STANDARD EVENT NAMES
# ══════════════════════════════════════════════════════════════════════════════

class Events:
    """
    Standardiserade event-namn för konsistens.
    """

    # Application lifecycle
    APP_STARTING = "app:starting"
    APP_READY = "app:ready"
    APP_SHUTDOWN = "app:shutdown"

    # Plugin lifecycle
    PLUGIN_LOADED = "plugin:loaded"
    PLUGIN_INITIALIZED = "plugin:initialized"
    PLUGIN_ACTIVATED = "plugin:activated"
    PLUGIN_DEACTIVATED = "plugin:deactivated"
    PLUGIN_ERROR = "plugin:error"

    # Vehicle events
    VEHICLE_CREATED = "vehicle:created"
    VEHICLE_UPDATED = "vehicle:updated"
    VEHICLE_DELETED = "vehicle:deleted"
    VEHICLE_MATCHED = "vehicle:matched"
    VEHICLE_UNMATCHED = "vehicle:unmatched"
    VEHICLE_SELECTED = "vehicle:selected"
    VEHICLE_VALIDATED = "vehicle:validated"

    # SAP events
    SAP_IMPORT_STARTED = "sap:import_started"
    SAP_IMPORT_COMPLETE = "sap:import_complete"
    SAP_IMPORT_ERROR = "sap:import_error"
    SAP_LOOKUP = "sap:lookup"
    SAP_MATCH = "sap:match"

    # TS (Transportstyrelsen) events
    TS_FILE_GENERATED = "ts:file_generated"
    TS_RESPONSE_RECEIVED = "ts:response_received"
    TS_ERROR = "ts:error"
    TS_SPEC_LOADED = "ts:spec_loaded"

    # TS Schema events
    TS_SCHEMA_LOADED = "ts:schema:loaded"
    TS_SCHEMA_VALIDATED = "ts:schema:validated"
    TS_SCHEMA_ERROR = "ts:schema:error"
    TS_SCHEMA_EVENTS_REGISTERED = "ts:schema:events_registered"

    # TS Post events
    TS_POST_PT28 = "ts:post:pt28"
    TS_POST_PT45 = "ts:post:pt45"
    TS_POST_PT99 = "ts:post:pt99"

    # UI events
    UI_REFRESH = "ui:refresh"
    UI_STATUS_CHANGED = "ui:status_changed"
    UI_PROGRESS = "ui:progress"
    UI_ERROR = "ui:error"
    UI_NOTIFICATION = "ui:notification"

    # Data events
    DATA_CHANGED = "data:changed"
    DATA_SAVED = "data:saved"
    DATA_LOADED = "data:loaded"
    DATA_IMPORT = "data:import"
    DATA_EXPORT = "data:export"

    # Error events
    ERROR_OCCURRED = "error:occurred"
    ERROR_HANDLED = "error:handled"
    ERROR_FATAL = "error:fatal"


# ══════════════════════════════════════════════════════════════════════════════
# FACTORY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def create_event_bus(
    collect_stats: bool = True,
    enable_schema_validation: bool = True,
    add_logging_middleware: bool = False
) -> EventBus:
    """
    Factory function för att skapa EventBus.
    """
    bus = EventBus(
        collect_stats=collect_stats,
        enable_schema_validation=enable_schema_validation
    )

    if add_logging_middleware:
        bus.add_middleware(LoggingMiddleware())

    return bus


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Classes
    "EventBus",
    "Priority",
    "Subscriber",
    "EventData",
    "EventStats",
    "EventTransaction",
    "Events",

    # Middleware
    "SchemaValidationMiddleware",
    "LoggingMiddleware",

    # Protocols
    "SchemaProvider",
    "EventMiddleware",

    # Decorators
    "on_event",
    "schema_event",
    "cancellable_event",

    # Factory
    "create_event_bus",

    # Constants
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]