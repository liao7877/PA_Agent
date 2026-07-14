from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PyQt6")

from pa_agent.gui.ai_stream_window import AIStreamPanel


class _BlockingSession:
    def __init__(self) -> None:
        self.started = threading.Event()

    def send(self, user_text, cancel_token, **kwargs):
        self.started.set()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if cancel_token is not None and cancel_token.is_set():
                break
            time.sleep(0.01)
        reply = MagicMock()
        reply.content = "ok"
        reply.reasoning_content = ""
        reply.usage = None
        return reply


def test_retry_status_updates_phase_without_crashing(qtbot):
    panel = AIStreamPanel()
    qtbot.addWidget(panel)

    panel.on_stage_prompt_ready("stage1", "", "")
    panel.mark_retry("stage1")

    assert "重试中" in panel._phase_label.text()


def test_shutdown_waits_for_free_chat_worker(qtbot):
    from pa_agent.util.threading import CancelToken

    panel = AIStreamPanel()
    qtbot.addWidget(panel)
    session = _BlockingSession()
    panel.set_session(session, CancelToken())
    panel._input_edit.setPlainText("hello")

    panel._on_send_or_stop()
    assert session.started.wait(timeout=2.0)

    worker = panel._worker
    assert worker is not None
    panel.shutdown(wait_ms=2_000)

    assert panel._worker is None
    assert not worker.isRunning()
