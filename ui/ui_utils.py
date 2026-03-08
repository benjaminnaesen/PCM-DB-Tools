"""
UI utility functions for PCM Database Tools.

Provides ``run_async`` — a helper that runs a blocking callable in a
background thread while displaying a modal progress dialog.  The result
is delivered back to the GUI thread via a Qt signal so that the caller
can safely update widgets.
"""

import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QDialog, QLabel, QMessageBox, QProgressBar, QVBoxLayout,
)


class _WorkerSignals(QObject):
    """Thread-safe signals emitted by the background worker."""
    finished = Signal(object)
    error = Signal(str)


def run_async(parent, task, callback, message):
    """Run *task* in a daemon thread with a modal progress dialog.

    Args:
        parent:   Parent QWidget (dialog is centered on it).
        task:     Callable executed in the background thread.
        callback: Called with the task result on success (GUI thread).
        message:  Text shown in the progress dialog.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle("Please wait\u2026")
    dialog.setFixedSize(300, 100)
    dialog.setModal(True)

    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(message))
    progress = QProgressBar()
    progress.setRange(0, 0)  # indeterminate
    layout.addWidget(progress)

    signals = _WorkerSignals()

    def _on_finished(result):
        dialog.accept()
        try:
            callback(result)
        except Exception as exc:
            QMessageBox.critical(parent, "Error", str(exc))

    def _on_error(err_msg):
        dialog.accept()
        QMessageBox.critical(parent, "Error", err_msg)

    signals.finished.connect(_on_finished)
    signals.error.connect(_on_error)

    def _thread_target():
        try:
            result = task()
            signals.finished.emit(result)
        except Exception as exc:
            signals.error.emit(str(exc))

    threading.Thread(target=_thread_target, daemon=True).start()
    dialog.exec()
