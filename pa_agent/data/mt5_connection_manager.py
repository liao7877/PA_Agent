"""Process-wide serialized owner for the MetaTrader 5 Python API.

The MetaTrader5 package exposes one process-global IPC session.  This module
keeps that lifecycle behind a single worker thread so independent data-source
objects cannot initialize, use, or shut down the terminal concurrently.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from concurrent.futures import (
    CancelledError as FutureCancelledError,
    Future,
    InvalidStateError,
    TimeoutError as FutureTimeoutError,
)
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from pa_agent.data.base import DataSourceTransientError

logger = logging.getLogger(__name__)

_T = TypeVar("_T")
_STOP = object()


@dataclass
class _Request:
    call: Callable[[], Any]
    future: Future[Any]


class MT5ConnectionManager:
    """Own and serialize the process-global MetaTrader5 connection."""

    def __init__(
        self,
        *,
        initialize_attempts: int = 3,
        backoff_initial_s: float = 0.5,
        backoff_max_s: float = 5.0,
        request_timeout_s: float = 10.0,
    ) -> None:
        self._initialize_attempts = max(1, int(initialize_attempts))
        self._backoff_initial_s = max(0.0, float(backoff_initial_s))
        self._backoff_max_s = max(0.0, float(backoff_max_s))
        self._request_timeout_s = max(0.1, float(request_timeout_s))
        self._requests: queue.Queue[_Request | object] = queue.Queue()
        self._state_lock = threading.RLock()
        self._leases: set[str] = set()
        self._symbol_holders: dict[str, set[str]] = {}
        self._terminal_path = ""
        self._ready = False
        self._stopping = False
        self._worker = threading.Thread(
            target=self._worker_main,
            name="pa-agent-mt5-owner",
            daemon=True,
        )
        self._worker.start()

    @property
    def is_ready(self) -> bool:
        with self._state_lock:
            return self._ready

    @property
    def lease_count(self) -> int:
        with self._state_lock:
            return len(self._leases)

    @property
    def is_worker_alive(self) -> bool:
        return self._worker.is_alive()

    def acquire(self, holder: str, terminal_path: str = "") -> None:
        holder = str(holder or "").strip()
        if not holder:
            raise ValueError("MT5 lease holder must be non-empty")
        requested_path = str(terminal_path or "").strip()
        with self._state_lock:
            if holder in self._leases:
                return
            if self._terminal_path and requested_path and requested_path != self._terminal_path:
                raise DataSourceTransientError(
                    "MT5 terminal path conflicts with the process-wide active connection: "
                    f"{requested_path!r} != {self._terminal_path!r}"
                )
            effective_path = self._terminal_path or requested_path

        # Commit the lease only after the worker has proved full readiness.
        self._submit(lambda: self._ensure_ready_impl(effective_path))
        with self._state_lock:
            self._terminal_path = effective_path
            self._leases.add(holder)

    def release(self, holder: str) -> None:
        holder = str(holder or "").strip()
        with self._state_lock:
            if holder not in self._leases:
                return
            self._leases.remove(holder)
            self._remove_holder_symbols_locked(holder)
            should_disconnect = not self._leases
        if should_disconnect and self._worker.is_alive():
            try:
                self._submit(self._disconnect_impl)
            finally:
                with self._state_lock:
                    self._terminal_path = ""
                    self._symbol_holders.clear()
                    self._ready = False

    def ensure_symbol_selected(self, holder: str, symbol: str | None = None) -> None:
        # Compatibility: callers predating holder-aware ownership may pass only symbol.
        if symbol is None:
            symbol = holder
            holder = "__legacy__"
        holder_name = str(holder or "").strip()
        name = str(symbol or "").strip()
        if not holder_name:
            raise ValueError("MT5 symbol holder must be non-empty")
        if not name:
            raise DataSourceTransientError("MT5 symbol is empty")
        with self._state_lock:
            already_owned = holder_name in self._symbol_holders.get(name, set())
        if already_owned:
            return
        self._submit(lambda: self._call_ready_impl(lambda mt5: self._select_symbol_impl(mt5, name)))
        with self._state_lock:
            self._symbol_holders.setdefault(name, set()).add(holder_name)

    def remove_symbol(self, holder: str, symbol: str | None = None) -> None:
        # Compatibility: a symbol-only call removes the legacy registration only.
        if symbol is None:
            symbol = holder
            holder = "__legacy__"
        holder_name = str(holder or "").strip()
        name = str(symbol or "").strip()
        if not holder_name or not name:
            return
        with self._state_lock:
            holders = self._symbol_holders.get(name)
            if holders is None:
                return
            holders.discard(holder_name)
            if not holders:
                self._symbol_holders.pop(name, None)

    def _remove_holder_symbols_locked(self, holder: str) -> None:
        empty: list[str] = []
        for symbol, holders in self._symbol_holders.items():
            holders.discard(holder)
            if not holders:
                empty.append(symbol)
        for symbol in empty:
            self._symbol_holders.pop(symbol, None)

    def symbol_exists(self, symbol: str) -> bool:
        name = str(symbol or "").strip()
        if not name:
            return False
        return bool(self._submit(lambda: self._call_ready_impl(lambda mt5: mt5.symbol_info(name) is not None)))

    def list_symbols(self) -> list[str]:
        def _list(mt5: Any) -> list[str]:
            symbols = mt5.symbols_get()
            return [str(item.name) for item in symbols or ()]

        return list(self._submit(lambda: self._call_ready_impl(_list)))

    def symbol_tick(self, symbol: str) -> Any:
        name = str(symbol or "").strip()
        if not name:
            return None
        return self._submit(lambda: self._call_ready_impl(lambda mt5: mt5.symbol_info_tick(name)))

    def timeframe_constant(self, name: str) -> Any:
        def _get(mt5: Any) -> Any:
            try:
                return getattr(mt5, name)
            except AttributeError as exc:
                raise DataSourceTransientError(
                    f"MT5 timeframe constant {name!r} not found"
                ) from exc

        return self._submit(lambda: self._call_ready_impl(_get))

    def copy_rates_from_pos(
        self,
        symbol: str,
        timeframe: Any,
        start_pos: int,
        count: int,
    ) -> Any:
        name = str(symbol or "").strip()

        def _copy(mt5: Any) -> Any:
            self._select_symbol_impl(mt5, name)
            rates = mt5.copy_rates_from_pos(name, timeframe, start_pos, count)
            if rates is None or len(rates) == 0:
                error = mt5.last_error()
                raise DataSourceTransientError(
                    f"MT5 copy_rates_from_pos failed for {name}: {error}"
                )
            return rates

        return self._submit(lambda: self._call_ready_impl(_copy, retry_operation=True))

    def force_shutdown(self) -> bool:
        stopped = self.stop(disconnect=True)
        if stopped:
            with self._state_lock:
                self._leases.clear()
                self._symbol_holders.clear()
                self._terminal_path = ""
                self._ready = False
        return stopped

    def stop(self, *, disconnect: bool = True) -> bool:
        with self._state_lock:
            if self._stopping:
                return not self._worker.is_alive()
            self._stopping = True
            queued = self._cancel_queued_requests_locked()
            self._requests.put(_STOP)
        if queued:
            logger.debug("Cancelled %d queued MT5 request(s) during stop", queued)
        if self._worker.is_alive():
            self._worker.join(timeout=self._request_timeout_s)
        if self._worker.is_alive():
            logger.warning("MT5 owner worker did not stop within %.1fs", self._request_timeout_s)
            return False
        if disconnect:
            with self._state_lock:
                self._ready = False
        return True

    def _cancel_queued_requests_locked(self) -> int:
        cancelled = 0
        retained_stop = False
        while True:
            try:
                item = self._requests.get_nowait()
            except queue.Empty:
                break
            if item is _STOP:
                retained_stop = True
                continue
            assert isinstance(item, _Request)
            if item.future.cancel():
                cancelled += 1
        if retained_stop:
            self._requests.put(_STOP)
        return cancelled

    def _submit(self, call: Callable[[], _T]) -> _T:
        future: Future[_T] = Future()
        with self._state_lock:
            if self._stopping or not self._worker.is_alive():
                raise DataSourceTransientError("MT5 connection owner is stopped")
            self._requests.put(_Request(call=call, future=future))
        try:
            return future.result(timeout=self._request_timeout_s)
        except FutureTimeoutError as exc:
            future.cancel()
            raise DataSourceTransientError(
                f"MT5 request timed out after {self._request_timeout_s:.1f}s"
            ) from exc
        except FutureCancelledError as exc:
            raise DataSourceTransientError("MT5 request cancelled during shutdown") from exc

    def _worker_main(self) -> None:
        try:
            while True:
                item = self._requests.get()
                if item is _STOP:
                    break
                assert isinstance(item, _Request)
                if not item.future.set_running_or_notify_cancel():
                    continue
                try:
                    result = item.call()
                except BaseException as exc:  # propagate exact typed data-source errors
                    try:
                        item.future.set_exception(exc)
                    except InvalidStateError:
                        logger.debug("MT5 request result discarded after caller cancellation")
                else:
                    try:
                        item.future.set_result(result)
                    except InvalidStateError:
                        logger.debug("MT5 request result discarded after caller cancellation")
        finally:
            try:
                self._disconnect_impl()
            except BaseException as exc:  # noqa: BLE001
                logger.debug("MT5 final disconnect failed: %s", exc)
            with self._state_lock:
                self._ready = False

    @staticmethod
    def _import_mt5() -> Any:
        try:
            import MetaTrader5 as mt5  # type: ignore[import]
        except ImportError as exc:
            raise DataSourceTransientError(
                "MetaTrader5 package not installed — run: pip install MetaTrader5"
            ) from exc
        return mt5

    def _ensure_ready_impl(self, terminal_path: str) -> None:
        mt5 = self._import_mt5()
        if self._ready:
            try:
                self._validate_readiness_impl(mt5)
                return
            except DataSourceTransientError:
                with self._state_lock:
                    self._ready = False
                try:
                    mt5.shutdown()
                except Exception:  # noqa: BLE001
                    pass

        last_error: BaseException | None = None
        for attempt in range(1, self._initialize_attempts + 1):
            try:
                init_kwargs: dict[str, str] = {}
                if terminal_path:
                    from pa_agent.data.mt5 import resolve_mt5_terminal_executable

                    resolved = resolve_mt5_terminal_executable(terminal_path)
                    if resolved:
                        init_kwargs["path"] = resolved
                if not mt5.initialize(**init_kwargs):
                    error = mt5.last_error()
                    raise DataSourceTransientError(
                        f"MT5 initialize() failed: {error}. "
                        "Make sure MetaTrader 5 terminal is open and logged in."
                    )
                self._validate_readiness_impl(mt5)
                with self._state_lock:
                    self._ready = True
                self._reselect_symbols_impl(mt5)
                logger.info("MT5 process-wide connection ready")
                return
            except BaseException as exc:
                last_error = exc
                with self._state_lock:
                    self._ready = False
                try:
                    mt5.shutdown()
                except Exception:  # noqa: BLE001
                    pass
                if attempt < self._initialize_attempts:
                    delay = min(
                        self._backoff_initial_s * (2 ** (attempt - 1)),
                        self._backoff_max_s,
                    )
                    if delay > 0:
                        time.sleep(delay)

        if isinstance(last_error, DataSourceTransientError):
            raise last_error
        raise DataSourceTransientError(f"MT5 readiness failed: {last_error}")

    @staticmethod
    def _validate_readiness_impl(mt5: Any) -> None:
        info = mt5.terminal_info()
        if info is None:
            raise DataSourceTransientError("MT5 terminal info unavailable")
        if getattr(info, "connected", True) is not True:
            raise DataSourceTransientError("MT5 terminal is not connected to the broker")
        account = mt5.account_info()
        if account is None:
            raise DataSourceTransientError("MT5 account is unavailable or not authorized")

    def _call_ready_impl(
        self,
        operation: Callable[[Any], _T],
        *,
        retry_operation: bool = False,
    ) -> _T:
        mt5 = self._import_mt5()
        try:
            self._validate_readiness_impl(mt5)
        except DataSourceTransientError:
            self._disconnect_impl()
            self._ensure_ready_impl(self._terminal_path)
            mt5 = self._import_mt5()
        try:
            return operation(mt5)
        except DataSourceTransientError:
            if not retry_operation:
                raise
            self._disconnect_impl()
            self._ensure_ready_impl(self._terminal_path)
            return operation(self._import_mt5())

    def _select_symbol_impl(self, mt5: Any, symbol: str) -> None:
        if mt5.symbol_info(symbol) is None:
            raise DataSourceTransientError(f"MT5 symbol unavailable: {symbol}")
        if not mt5.symbol_select(symbol, True):
            error = mt5.last_error()
            raise DataSourceTransientError(
                f"MT5 symbol_select failed for {symbol}: {error}"
            )

    def _reselect_symbols_impl(self, mt5: Any) -> None:
        with self._state_lock:
            symbols = tuple(self._symbol_holders)
        for symbol in symbols:
            self._select_symbol_impl(mt5, symbol)

    def _disconnect_impl(self) -> None:
        mt5 = self._import_mt5()
        if self._ready:
            try:
                mt5.shutdown()
            finally:
                with self._state_lock:
                    self._ready = False
        else:
            with self._state_lock:
                self._ready = False


_instance: MT5ConnectionManager | None = None
_instance_lock = threading.Lock()


def configure_mt5_connection_manager(**kwargs: Any) -> MT5ConnectionManager:
    """Create/configure the singleton before any MT5Source acquires a lease."""
    global _instance
    with _instance_lock:
        if _instance is None or not _instance.is_worker_alive:
            _instance = MT5ConnectionManager(**kwargs)
            return _instance
        if _instance.lease_count:
            return _instance
        # An idle manager can be replaced so freshly loaded settings take effect.
        old = _instance
        if old.force_shutdown():
            _instance = MT5ConnectionManager(**kwargs)
        return _instance


def get_mt5_connection_manager(**kwargs: Any) -> MT5ConnectionManager:
    """Return the process-wide MT5 owner."""
    global _instance
    if _instance is None or not _instance.is_worker_alive:
        with _instance_lock:
            if _instance is None or not _instance.is_worker_alive:
                _instance = MT5ConnectionManager(**kwargs)
    return _instance


def reset_mt5_connection_manager() -> None:
    """Stop and discard the singleton. Intended for tests and app shutdown."""
    global _instance
    with _instance_lock:
        instance = _instance
        if instance is None:
            return
        stopped = instance.force_shutdown()
        if stopped and _instance is instance:
            _instance = None
    if not stopped:
        raise DataSourceTransientError(
            "MT5 connection owner did not stop; refusing to create a second owner"
        )
