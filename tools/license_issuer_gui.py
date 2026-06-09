#!/usr/bin/env python3
"""PA Agent 激活码可视化签发工具（供应商专用）。"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pa_agent.licensing.issuer import (
    DEFAULT_PRIVATE_KEY,
    DEFAULT_PUBLIC_KEY,
    IssuedLicense,
    generate_keypair,
    issue_license,
    verify_license_token,
)
from pa_agent.licensing.validator import LicenseValidator


def _settings_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".pa_agent_issuer"
    path = base / "PA_Agent_Issuer"
    path.mkdir(parents=True, exist_ok=True)
    return path / "settings.json"


def _load_settings() -> dict:
    path = _settings_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_settings(data: dict) -> None:
    _settings_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class LicenseIssuerWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PA Agent 激活码签发工具")
        self.resize(760, 620)

        self._settings = _load_settings()
        tabs = QTabWidget()
        tabs.addTab(self._build_issue_tab(), "签发激活码")
        tabs.addTab(self._build_verify_tab(), "验证激活码")
        tabs.addTab(self._build_keys_tab(), "密钥管理")
        self.setCentralWidget(tabs)

        hint = QLabel("供应商专用工具 · 私钥仅保存在本机，切勿随安装包分发")
        hint.setStyleSheet("color: #888; padding: 6px 10px;")
        status = self.statusBar()
        if status is not None:
            status.addPermanentWidget(hint)

    def _build_issue_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form_box = QGroupBox("签发参数")
        form = QFormLayout(form_box)

        self._private_key_edit = QLineEdit(self._settings.get("private_key_path", str(DEFAULT_PRIVATE_KEY)))
        browse_btn = QPushButton("浏览…")
        browse_btn.clicked.connect(self._browse_private_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self._private_key_edit, 1)
        key_row.addWidget(browse_btn)
        form.addRow("私钥文件", key_row)

        self._holder_edit = QLineEdit()
        self._holder_edit.setPlaceholderText("客户名称或备注（可选）")
        form.addRow("客户备注", self._holder_edit)

        self._machine_mode = QComboBox()
        self._machine_mode.addItem("不绑定（任意设备）", "any")
        self._machine_mode.addItem("绑定指定机器码", "custom")
        self._machine_mode.currentIndexChanged.connect(self._on_machine_mode_changed)
        form.addRow("机器绑定", self._machine_mode)

        self._machine_edit = QLineEdit()
        self._machine_edit.setPlaceholderText("16 位机器码，可含连字符")
        self._machine_edit.setEnabled(False)
        form.addRow("目标机器码", self._machine_edit)

        self._expiry_mode = QComboBox()
        self._expiry_mode.addItem("按有效天数", "days")
        self._expiry_mode.addItem("指定到期日期", "date")
        self._expiry_mode.currentIndexChanged.connect(self._on_expiry_mode_changed)
        form.addRow("到期方式", self._expiry_mode)

        self._days_spin = QSpinBox()
        self._days_spin.setRange(1, 3650)
        self._days_spin.setValue(int(self._settings.get("default_days", 30)))
        form.addRow("有效天数", self._days_spin)

        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDate(QDate.currentDate().addDays(30))
        self._date_edit.setEnabled(False)
        form.addRow("到期日期", self._date_edit)

        issue_btn = QPushButton("生成激活码")
        issue_btn.setStyleSheet("font-weight: 600; padding: 8px 16px;")
        issue_btn.clicked.connect(self._on_issue)

        result_box = QGroupBox("签发结果")
        result_layout = QVBoxLayout(result_box)
        self._result_meta = QLabel("尚未签发")
        self._result_meta.setWordWrap(True)
        self._token_output = QTextEdit()
        self._token_output.setReadOnly(True)
        self._token_output.setMinimumHeight(120)
        self._token_output.setFont(QFont("Consolas", 10))
        copy_btn = QPushButton("复制激活码")
        copy_btn.clicked.connect(self._copy_token)
        result_layout.addWidget(self._result_meta)
        result_layout.addWidget(self._token_output)
        result_layout.addWidget(copy_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(form_box)
        layout.addWidget(issue_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(result_box, 1)
        return tab

    def _build_verify_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("粘贴客户提供的激活码进行校验："))
        self._verify_input = QTextEdit()
        self._verify_input.setPlaceholderText("PAAG-...")
        self._verify_input.setMinimumHeight(120)
        self._verify_input.setFont(QFont("Consolas", 10))
        verify_btn = QPushButton("验证激活码")
        verify_btn.clicked.connect(self._on_verify)
        self._verify_result = QLabel("")
        self._verify_result.setWordWrap(True)
        layout.addWidget(self._verify_input)
        layout.addWidget(verify_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._verify_result, 1)
        return tab

    def _build_keys_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info = QLabel(
            "首次使用可在此生成 Ed25519 密钥对。\n"
            "私钥用于签发，公钥需复制到 PA Agent 项目的 pa_agent/licensing/public_key.pem 后重新打包主程序。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form_box = QGroupBox("生成新密钥对")
        form = QFormLayout(form_box)

        self._new_private_edit = QLineEdit(str(DEFAULT_PRIVATE_KEY))
        self._new_public_edit = QLineEdit(str(DEFAULT_PUBLIC_KEY))
        priv_browse = QPushButton("浏览…")
        pub_browse = QPushButton("浏览…")
        priv_browse.clicked.connect(lambda: self._browse_save_path(self._new_private_edit, "保存私钥"))
        pub_browse.clicked.connect(lambda: self._browse_save_path(self._new_public_edit, "保存公钥"))

        priv_row = QHBoxLayout()
        priv_row.addWidget(self._new_private_edit, 1)
        priv_row.addWidget(priv_browse)
        pub_row = QHBoxLayout()
        pub_row.addWidget(self._new_public_edit, 1)
        pub_row.addWidget(pub_browse)
        form.addRow("私钥保存路径", priv_row)
        form.addRow("公钥保存路径", pub_row)

        gen_btn = QPushButton("生成密钥对")
        gen_btn.clicked.connect(self._on_generate_keys)
        layout.addWidget(form_box)
        layout.addWidget(gen_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return tab

    def _browse_private_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择私钥文件",
            str(Path(self._private_key_edit.text()).parent),
            "PEM Files (*.pem);;All Files (*)",
        )
        if path:
            self._private_key_edit.setText(path)

    def _browse_save_path(self, target: QLineEdit, title: str) -> None:
        path, _ = QFileDialog.getSaveFileName(self, title, target.text(), "PEM Files (*.pem)")
        if path:
            if not path.lower().endswith(".pem"):
                path += ".pem"
            target.setText(path)

    def _on_machine_mode_changed(self) -> None:
        custom = self._machine_mode.currentData() == "custom"
        self._machine_edit.setEnabled(custom)

    def _on_expiry_mode_changed(self) -> None:
        by_date = self._expiry_mode.currentData() == "date"
        self._days_spin.setEnabled(not by_date)
        self._date_edit.setEnabled(by_date)

    def _persist_issue_settings(self) -> None:
        self._settings["private_key_path"] = self._private_key_edit.text().strip()
        self._settings["default_days"] = self._days_spin.value()
        _save_settings(self._settings)

    def _issue_params(self) -> tuple[Path, str, str | None, datetime | None, int]:
        private_path = Path(self._private_key_edit.text().strip())
        machine = "any"
        if self._machine_mode.currentData() == "custom":
            machine = self._machine_edit.text().strip() or "any"
        expires: datetime | None = None
        days = self._days_spin.value()
        if self._expiry_mode.currentData() == "date":
            qd = self._date_edit.date()
            expires = datetime(qd.year(), qd.month(), qd.day(), 23, 59, 59, tzinfo=timezone.utc)
        return private_path, self._holder_edit.text().strip(), machine, expires, days

    def _show_issued(self, issued: IssuedLicense) -> None:
        self._result_meta.setText(
            f"授权 ID：{issued.license_id}\n"
            f"客户备注：{issued.holder or '—'}\n"
            f"到期时间：{issued.expires_at_utc}\n"
            f"机器绑定：{issued.machine_label}"
        )
        self._token_output.setPlainText(issued.token)

    def _on_issue(self) -> None:
        try:
            private_path, holder, machine, expires, days = self._issue_params()
            issued = issue_license(
                private_key_path=private_path,
                days=days,
                expires=expires,
                machine=machine,
                holder=holder,
            )
        except FileNotFoundError as exc:
            QMessageBox.warning(self, "签发失败", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "签发失败", str(exc))
            return

        self._persist_issue_settings()
        self._show_issued(issued)
        self.statusBar().showMessage("激活码已生成", 5000)

    def _copy_token(self) -> None:
        token = self._token_output.toPlainText().strip()
        if not token:
            return
        QGuiApplication.clipboard().setText(token)
        self.statusBar().showMessage("激活码已复制到剪贴板", 3000)

    def _on_verify(self) -> None:
        token = self._verify_input.toPlainText().strip()
        if not token:
            QMessageBox.information(self, "验证", "请先粘贴激活码。")
            return
        info = verify_license_token(token)
        expiry = LicenseValidator.format_expiry(info.expires_at)
        if info.ok:
            text = (
                f"✅ {info.message}\n"
                f"授权 ID：{info.license_id or '—'}\n"
                f"到期时间：{expiry}\n"
                f"剩余天数：{info.days_remaining} 天"
            )
            color = "#3ddc84"
        else:
            text = f"❌ {info.message}"
            color = "#ff6b6b"
        self._verify_result.setText(text)
        self._verify_result.setStyleSheet(f"color: {color}; font-size: 13px;")

    def _on_generate_keys(self) -> None:
        private_path = Path(self._new_private_edit.text().strip())
        public_path = Path(self._new_public_edit.text().strip())
        if not private_path or not public_path:
            QMessageBox.warning(self, "生成密钥", "请填写私钥与公钥保存路径。")
            return
        if private_path.exists() or public_path.exists():
            answer = QMessageBox.question(
                self,
                "覆盖确认",
                "目标路径已存在文件，是否覆盖？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            priv, pub = generate_keypair(private_path=private_path, public_path=public_path)
        except Exception as exc:
            QMessageBox.critical(self, "生成失败", str(exc))
            return
        self._private_key_edit.setText(str(priv))
        self._persist_issue_settings()
        QMessageBox.information(
            self,
            "生成成功",
            f"私钥：{priv}\n公钥：{pub}\n\n请将公钥复制到 PA Agent 项目后重新打包主程序。",
        )


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PA Agent License Issuer")
    app.setStyle("Fusion")
    window = LicenseIssuerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
