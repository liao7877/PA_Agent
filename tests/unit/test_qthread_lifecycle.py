from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QThread

from pa_agent.data.refresh_loop import RefreshLoop
from pa_agent.gui.ai_stream_window import _ChatWorker as StreamChatWorker
from pa_agent.gui.analysis_prep_worker import AnalysisPrepWorker
from pa_agent.gui.conversation_widget import _ChatWorker as ConversationChatWorker
from pa_agent.gui.main_window import _AnalysisWorker
from pa_agent.gui.snapshot_worker import SnapshotFetchWorker


@pytest.mark.parametrize(
    "worker_cls",
    [
        RefreshLoop,
        StreamChatWorker,
        AnalysisPrepWorker,
        ConversationChatWorker,
        _AnalysisWorker,
        SnapshotFetchWorker,
    ],
)
def test_qthread_subclasses_do_not_shadow_finished_signal(worker_cls):
    """Result payloads must not replace QThread.finished lifecycle semantics.

    Cleanup slots rely on ``QThread.finished`` meaning that ``run()`` has fully
    returned.  Shadowing it with a custom payload signal can schedule
    ``deleteLater()`` while the native thread is still running, which makes Qt
    abort the whole process with 0xc0000409 on Windows.
    """

    assert issubclass(worker_cls, QThread)
    assert "finished" not in worker_cls.__dict__


def test_payload_signals_are_separate_from_thread_completion():
    assert "result_ready" in _AnalysisWorker.__dict__
    assert "reply_ready" in StreamChatWorker.__dict__
    assert "reply_ready" in ConversationChatWorker.__dict__
