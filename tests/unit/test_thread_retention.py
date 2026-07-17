from __future__ import annotations

import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QThread

from pa_agent.gui.main_window import _ORPHANED_THREADS, _retain_running_thread


class _SlowThread(QThread):
    def run(self) -> None:
        time.sleep(0.05)


def test_retain_running_thread_keeps_reference_until_finished(qtbot):
    worker = _SlowThread()
    worker.start()

    _retain_running_thread(worker)

    assert worker in _ORPHANED_THREADS
    assert worker.wait(2_000)
    qtbot.waitUntil(lambda: worker not in _ORPHANED_THREADS, timeout=2_000)
