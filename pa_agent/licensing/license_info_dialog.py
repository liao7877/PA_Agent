"""About / license information and renewal dialog."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from pa_agent.licensing.activation_dialog import ActivationDialog
from pa_agent.licensing.client_config import load_license_client_config
from pa_agent.licensing.machine_id import format_machine_code
from pa_agent.licensing.validator import LicenseInfo, LicenseValidator


class LicenseInfoDialog(QDialog):
    def __init__(self, validator: LicenseValidator, parent=None) -> None:
        super().__init__(parent)
        self._validator = validator
        self.setWindowTitle("授权信息")
        self.setModal(True)
        self.setMinimumWidth(480)

        self._title = QLabel("PA Agent 授权状态")
        self._title.setStyleSheet("font-size: 14px; font-weight: 600;")

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)

        self._mode_label = QLabel()
        self._license_id_label = QLabel()
        self._expiry_label = QLabel()
        self._days_label = QLabel()
        self._machine_label = QLabel()
        self._machine_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        form = QFormLayout()
        form.addRow("授权模式", self._mode_label)
        form.addRow("授权 ID", self._license_id_label)
        form.addRow("到期时间", self._expiry_label)
        form.addRow("剩余天数", self._days_label)
        form.addRow("本机机器码", self._machine_label)

        renew_btn = QPushButton("续期 / 输入新激活码…")
        renew_btn.clicked.connect(self._renew)

        copy_btn = QPushButton("复制机器码")
        copy_btn.clicked.connect(self._copy_machine)

        btn_row = QHBoxLayout()
        btn_row.addWidget(renew_btn)
        btn_row.addWidget(copy_btn)
        btn_row.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._status_label)
        layout.addLayout(form)
        layout.addLayout(btn_row)
        layout.addWidget(buttons)

        self._refresh()

    def _refresh(self) -> None:
        info = self._validator.check()
        cfg = load_license_client_config()
        mode = "在线 + 离线" if cfg.active else "离线"
        self._mode_label.setText(mode)
        self._status_label.setText(info.message)
        self._license_id_label.setText(info.license_id or "—")
        self._expiry_label.setText(LicenseValidator.format_expiry(info.expires_at))
        self._days_label.setText("—" if info.days_remaining is None else f"{info.days_remaining} 天")
        machine = info.machine_id or self._validator.current_machine_id()
        self._machine_label.setText(format_machine_code(machine))

        if info.ok:
            self._status_label.setStyleSheet("color: #3ddc84;")
        else:
            self._status_label.setStyleSheet("color: #ff6b6b;")

    def _copy_machine(self) -> None:
        from PyQt6.QtGui import QGuiApplication

        machine = self._validator.current_machine_id()
        QGuiApplication.clipboard().setText(format_machine_code(machine))

    def _renew(self) -> None:
        dialog = ActivationDialog(self._validator, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh()
