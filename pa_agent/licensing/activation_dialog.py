"""Activation dialog shown before the main window."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from pa_agent.licensing.machine_id import format_machine_code
from pa_agent.licensing.validator import LicenseInfo, LicenseValidator


class ActivationDialog(QDialog):
    def __init__(self, validator: LicenseValidator, parent=None) -> None:
        super().__init__(parent)
        self._validator = validator
        self._result_info: LicenseInfo | None = None

        self.setWindowTitle("Trading Agent 激活")
        self.setModal(True)
        self.setMinimumWidth(520)

        title = QLabel("请输入供应商提供的激活码以继续使用 Trading Agent")
        title.setWordWrap(True)

        machine = validator.current_machine_id()
        self._machine_label = QLabel(format_machine_code(machine))
        self._machine_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        copy_btn = QPushButton("复制机器码")
        copy_btn.clicked.connect(lambda: self._copy_machine_code(machine))

        machine_row = QHBoxLayout()
        machine_row.addWidget(self._machine_label, 1)
        machine_row.addWidget(copy_btn)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)

        self._token_edit = QLineEdit()
        self._token_edit.setPlaceholderText("PAAG:XXXXX:XXXXX:...")
        self._token_edit.setClearButtonEnabled(True)

        form = QFormLayout()
        form.addRow("本机机器码", machine_row)
        form.addRow("激活码", self._token_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_activate)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addWidget(self._status_label)
        layout.addWidget(buttons)

    @property
    def license_info(self) -> LicenseInfo | None:
        return self._result_info

    def _copy_machine_code(self, machine: str) -> None:
        from PyQt6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(format_machine_code(machine))
        self._status_label.setText("机器码已复制，请发送给供应商生成激活码。")

    def _on_activate(self) -> None:
        token = self._token_edit.text().strip()
        if not token:
            self._status_label.setText("请先输入激活码。")
            return
        info = self._validator.activate(token)
        if not info.ok:
            self._status_label.setText(info.message)
            return
        self._result_info = info
        self.accept()


def ensure_license_or_exit(app, validator: LicenseValidator | None = None) -> LicenseInfo:
    """Return valid license info or terminate the application."""
    validator = validator or LicenseValidator()
    info = validator.check()
    if info.ok:
        return info

    dialog = ActivationDialog(validator)
    if dialog.exec() != QDialog.DialogCode.Accepted or dialog.license_info is None:
        QMessageBox.critical(None, "未激活", "未检测到有效授权，程序将退出。")
        raise SystemExit(1)
    return dialog.license_info
