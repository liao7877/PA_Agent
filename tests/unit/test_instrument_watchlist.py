from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QComboBox, QListWidget, QListWidgetItem, QStatusBar

from pa_agent.config.settings import InstrumentSettings, Settings
from pa_agent.gui.instrument_settings_dialog import InstrumentSettingsDialog
from pa_agent.gui.main_window import MainWindow
from pa_agent.instruments import (
    InstrumentRuntimeManager,
    instrument_key,
    reorder_instrument_settings,
)


def _instrument(id_: str, symbol: str, timeframe: str = "15m") -> InstrumentSettings:
    return InstrumentSettings(id=id_, symbol=symbol, timeframe=timeframe)


def test_reorder_instrument_settings_follows_visual_key_order() -> None:
    items = [
        _instrument("gold", "XAUUSDm"),
        _instrument("euro", "EURUSD"),
        _instrument("pound", "GBPUSD"),
    ]

    reordered = reorder_instrument_settings(items, ["pound", "gold", "euro"])

    assert [instrument_key(item) for item in reordered] == ["pound", "gold", "euro"]
    assert {id(item) for item in reordered} == {id(item) for item in items}


@pytest.mark.parametrize(
    "ordered_keys",
    [
        ["gold", "euro"],
        ["gold", "euro", "unknown"],
        ["gold", "gold", "pound"],
    ],
)
def test_reorder_instrument_settings_rejects_incomplete_or_duplicate_order(
    ordered_keys: list[str],
) -> None:
    items = [
        _instrument("gold", "XAUUSDm"),
        _instrument("euro", "EURUSD"),
        _instrument("pound", "GBPUSD"),
    ]

    with pytest.raises(ValueError):
        reorder_instrument_settings(items, ordered_keys)


def test_instrument_settings_dialog_selects_initial_instrument(qtbot) -> None:
    settings = Settings()
    settings.instruments.items = [
        _instrument("gold", "XAUUSDm"),
        _instrument("euro", "EURUSD", "1h"),
    ]

    dialog = InstrumentSettingsDialog(settings, initial_key="euro")
    qtbot.addWidget(dialog)

    assert dialog._list.currentRow() == 1
    assert dialog._symbol_edit.text() == "EURUSD"
    assert dialog._tf_combo.currentText() == "1h"


def _watchlist_window(settings: Settings):
    manager = InstrumentRuntimeManager(settings=settings)
    window = MainWindow.__new__(MainWindow)
    window._ctx = MagicMock(settings=settings, instrument_manager=manager, data_source=None)
    window._watchlist = QListWidget()
    window._status_bar = QStatusBar()
    window._active_instrument_key = "gold"
    window._watchlist_rebuilding = False
    window._watchlist_reordering = False
    return window, manager


def test_watchlist_move_persists_order_without_reloading_runtimes(
    qtbot, monkeypatch
) -> None:
    settings = Settings()
    settings.instruments.items = [
        _instrument("gold", "XAUUSDm"),
        _instrument("euro", "EURUSD", "1h"),
        _instrument("pound", "GBPUSD", "5m"),
    ]
    window, manager = _watchlist_window(settings)
    qtbot.addWidget(window._watchlist)
    runtime_ids = {runtime.key: id(runtime) for runtime in manager.runtimes()}
    saved_orders: list[list[str]] = []
    monkeypatch.setattr(
        "pa_agent.config.settings.save_settings",
        lambda current: saved_orders.append(
            [instrument_key(item) for item in current.instruments.items]
        ),
    )
    for runtime in manager.runtimes():
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, runtime.key)
        window._watchlist.addItem(item)
    moved = window._watchlist.takeItem(2)
    window._watchlist.insertItem(0, moved)

    window._on_watchlist_rows_moved()

    assert saved_orders == [["pound", "gold", "euro"]]
    assert [runtime.key for runtime in manager.runtimes()] == ["pound", "gold", "euro"]
    assert {runtime.key: id(runtime) for runtime in manager.runtimes()} == runtime_ids
    assert window._active_instrument_key == "gold"


def test_activate_instrument_syncs_symbol_and_timeframe_candidates(qtbot) -> None:
    settings = Settings()
    settings.instruments.items = [
        _instrument("gold", "XAUUSDm"),
        _instrument("euro", "EURUSD", "1h"),
    ]
    window, manager = _watchlist_window(settings)
    window._instrument_switching = False
    window._active_data_source_kind = "mt5"
    window._data_source_combo = QComboBox()
    window._data_source_combo.addItem("MT5", "mt5")
    window._tv_exchange_combo = QComboBox()
    window._tv_exchange_combo.addItem("自动", "")
    window._symbol_combo = QComboBox()
    window._symbol_combo.setEditable(True)
    window._symbol_combo.addItem("XAUUSDm")
    window._tf_combo = QComboBox()
    window._tf_combo.addItems(["5m", "15m"])
    window._keep_analysis_checkbox = QCheckBox()
    window._populate_symbol_combo_for_source = MagicMock()
    window._populate_timeframe_combo_for_source = MagicMock()
    window._sync_tv_exchange_visibility = MagicMock()
    window._update_symbol_data_alert = MagicMock()
    window._refresh_api_key_ui_state = MagicMock()
    window._update_ai_mode_label = MagicMock()
    window._pull_chart_frame_from_source = MagicMock(return_value=None)
    window._chart_widget = MagicMock()
    window._update_submit_button_state = MagicMock()
    window._update_keep_analysis_status_display = MagicMock()

    window._activate_instrument("euro")

    assert window._active_instrument_key == "euro"
    assert window._symbol_combo.currentText() == "EURUSD"
    assert window._tf_combo.currentText() == "1h"
    window._populate_symbol_combo_for_source.assert_called_once_with()
    window._populate_timeframe_combo_for_source.assert_called_once_with()


def test_activate_instrument_does_not_persist_keep_analysis_as_user_input(qtbot) -> None:
    settings = Settings()
    settings.general.keep_analysis = False
    settings.instruments.items = [
        _instrument("gold", "XAUUSDm"),
        InstrumentSettings(
            id="euro", symbol="EURUSD", timeframe="1h", keep_analysis=True
        ),
    ]
    window, _manager = _watchlist_window(settings)
    window._instrument_switching = False
    window._active_data_source_kind = "mt5"
    window._data_source_combo = QComboBox()
    window._data_source_combo.addItem("MT5", "mt5")
    window._tv_exchange_combo = QComboBox()
    window._tv_exchange_combo.addItem("自动", "")
    window._symbol_combo = QComboBox()
    window._symbol_combo.setEditable(True)
    window._tf_combo = QComboBox()
    window._keep_analysis_checkbox = QCheckBox()
    window._keep_analysis_checkbox.stateChanged.connect(
        window._on_keep_analysis_checkbox_changed
    )
    window._wait_close_checkbox = QCheckBox()
    window._ensure_refresh_loop_running = MagicMock()
    window._set_chart_refresh_paused = MagicMock()
    window._populate_symbol_combo_for_source = MagicMock()
    window._populate_timeframe_combo_for_source = MagicMock()
    window._sync_tv_exchange_visibility = MagicMock()
    window._update_symbol_data_alert = MagicMock()
    window._refresh_api_key_ui_state = MagicMock()
    window._update_ai_mode_label = MagicMock()
    window._pull_chart_frame_from_source = MagicMock(return_value=None)
    window._chart_widget = MagicMock()
    window._update_submit_button_state = MagicMock()
    window._update_keep_analysis_status_display = MagicMock()

    window._activate_instrument("euro")

    assert window._keep_analysis_checkbox.isChecked()
    assert settings.general.keep_analysis is False
    window._ensure_refresh_loop_running.assert_not_called()


def test_stop_all_attempts_every_runtime_when_one_does_not_stop(monkeypatch) -> None:
    settings = Settings()
    settings.instruments.items = [
        _instrument("gold", "XAUUSDm"),
        _instrument("euro", "EURUSD"),
        _instrument("pound", "GBPUSD"),
    ]
    manager = InstrumentRuntimeManager(settings=settings)
    stopped: list[str] = []

    def stop_runtime(key: str, *, wait_ms: int = 5000) -> bool:
        stopped.append(key)
        return key != "gold"

    monkeypatch.setattr(manager, "stop_runtime", stop_runtime)

    assert manager.stop_all() is False
    assert stopped == ["gold", "euro", "pound"]
