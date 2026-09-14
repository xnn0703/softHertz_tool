"""KA_RF_UNIT V2 OTA 界面：只使用 Driver 语义接口与 Qt 信号。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from .driver import KaRfUnitDriver
from . import protocol as p


class OtaPanel(QWidget):
    """上传完成自动安装；界面不拥有传输状态机，不存在手工 COMMIT。"""

    busy_changed = Signal(bool)

    def __init__(self, driver: Optional[KaRfUnitDriver] = None, parent=None) -> None:
        """创建上传控件并绑定当前 Driver，未连接时禁止设备操作。"""
        super().__init__(parent)
        self._driver = None
        self._bindings = []
        self._connected = False
        self._busy = False
        layout = QVBoxLayout(self)
        warning = QLabel("仅支持 V2 / RS485 460800 8N1。开始上传即授权：完整传输结束后自动校验、安装并复位。"
                         "末尾 ACK 不代表安装成功；同版本重装无法单靠版本查询确认。")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("ka_rf_unit_app_<版本>_release.bin / beta.bin")
        self.browse_btn = QPushButton("选择固件")
        self.browse_btn.clicked.connect(self._browse)
        row.addWidget(self.file_edit, 1)
        row.addWidget(self.browse_btn)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.query_btn = QPushButton("查询升级状态")
        self.begin_btn = QPushButton("上传并自动安装")
        self.cancel_btn = QPushButton("取消上传")
        self.abort_btn = QPushButton("清理候选")
        for button, slot in ((self.query_btn, self._query), (self.begin_btn, self._begin),
                             (self.cancel_btn, self._cancel), (self.abort_btn, self._abort)):
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.state_label = QLabel("未连接")
        self.status_label = QLabel("尚未查询")
        self.status_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setMaximumHeight(130)
        for widget in (self.state_label, self.status_label, self.progress_bar, self.log):
            layout.addWidget(widget)
        self._bind_driver(driver)

    def _bind_driver(self, driver: Optional[KaRfUnitDriver]) -> None:
        """断开旧连接信号；排队的旧信号仍通过 sender 身份检查丢弃。"""
        for signal, slot in self._bindings:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._bindings.clear()
        self._driver = driver
        self._connected = bool(driver and driver.running)
        self._busy = bool(driver and getattr(driver, "ota_active", False))
        self.status_label.setText("新连接，尚未查询" if driver else "未连接")
        if driver:
            for name, slot in (
                ("ota_status_signal", self._status), ("ota_event_signal", self._event),
                ("ota_progress_signal", self._progress), ("ota_busy_signal", self._busy_update),
                ("opened_signal", self._opened), ("finished", self._finished)):
                signal = getattr(driver, name, None)
                if signal is not None:
                    signal.connect(slot)
                    self._bindings.append((signal, slot))
        self._buttons()
        self.busy_changed.emit(self._busy)

    def _current_sender(self) -> bool:
        """核对信号来源，过滤旧串口会话的排队事件。"""
        return self.sender() is self._driver

    def _buttons(self) -> None:
        """依据连接与占用状态设置按钮，禁止手工提交。"""
        idle = self._connected and not self._busy
        for button in (self.query_btn, self.begin_btn, self.abort_btn):
            button.setEnabled(idle)
        self.cancel_btn.setEnabled(self._connected and self._busy)
        self.file_edit.setEnabled(not self._busy)
        self.browse_btn.setEnabled(not self._busy)

    @Slot()
    def _browse(self) -> None:
        """选择本地 App BIN 路径，不自动上传。"""
        path, _ = QFileDialog.getOpenFileName(self, "选择 KA_RF_UNIT App BIN", "", "App BIN (*.bin)")
        if path:
            self.file_edit.setText(path)

    @Slot()
    def _query(self) -> None:
        """通过 Driver 查询 OTA 状态。"""
        if self._driver and not self._driver.ota_status():
            self.log.appendPlainText("查询未入队：串口不可用或 OTA 占用")

    @Slot()
    def _begin(self) -> None:
        """确认自动安装后限量读取文件，以 basename 启动 Driver 上传。"""
        if not self._driver or self._busy:
            return
        path = Path(self.file_edit.text().strip())
        try:
            if not path.is_file() or not 1 <= path.stat().st_size <= p.OTA_APP_MAX_SIZE:
                raise ValueError("请选择 1..786432 字节的 App BIN")
            if QMessageBox.question(
                    self, "确认自动安装", "完整上传后设备会自动安装并复位，是否开始？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            # 限量读取，避免选择过程中被替换的大文件占用内存。
            with path.open("rb") as handle:
                data = handle.read(p.OTA_APP_MAX_SIZE + 1)
            if not self._driver.start_ota(filename=path.name, data=data):
                self.log.appendPlainText("尚有在途请求或串口未就绪，请稍后重试")
                return
            self.progress_bar.setValue(0)
        except (OSError, ValueError) as exc:
            self.log.appendPlainText(str(exc))

    @Slot()
    def _cancel(self) -> None:
        """请求取消上传，保持独占直至设备恢复查询或断开。"""
        if self._driver:
            self._driver.stop_ota()

    @Slot()
    def _abort(self) -> None:
        """用户确认后在普通模式清理候选固件。"""
        if self._driver and not self._busy:
            if QMessageBox.question(
                    self, "清理候选", "清除设备候选固件？清理后需要重新上传。",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
                if not self._driver.ota_abort():
                    self.log.appendPlainText("清理请求未入队")

    @Slot(bool, str)
    def _opened(self, success: bool, message: str) -> None:
        """处理当前连接的串口打开结果。"""
        if self._current_sender():
            self._connected = success
            self.state_label.setText(message)
            self._buttons()

    @Slot()
    def _finished(self) -> None:
        """串口结束后禁用设备操作，不声称升级完成。"""
        if self._current_sender():
            self._connected = False
            self._busy = False
            self.state_label.setText("串口已关闭；安装结果以重新查询为准")
            self._buttons()
            self.busy_changed.emit(False)

    @Slot(bool)
    def _busy_update(self, busy: bool) -> None:
        """根据 Driver 占用信号同步本页及父页面互斥。"""
        if self._current_sender():
            self._busy = busy
            self._buttons()
            self.busy_changed.emit(busy)

    @Slot(dict)
    def _status(self, status: dict) -> None:
        """展示完整版本、阶段、健康、候选及最近自动安装失败原因。"""
        if not self._current_sender():
            return
        if status["result"] != p.RESULT_OK:
            self.status_label.setText("查询失败：" + p.result_text(status["result"]))
            return
        version = ".".join(str(status[k]) for k in ("fw_major", "fw_minor", "fw_revision"))
        health = ("PENDING 待稳定", "STABLE 稳定", "GRACEFUL_REBOOT 重启中")[status["app_boot_state"]]
        phase = ("空闲", "接收", "校验", "安装提交")[status["phase"]]
        failure = p.result_text(status["last_result"]) if status["last_result"] else "无（不代表安装成功）"
        self.status_label.setText(
            f"运行版本 {version} | {health} | {phase} | 升级请求 {status['update_requested']} | "
            f"候选 {status.get('filename', '无')} | 最近自动安装失败记录 {failure}")

    @Slot(str, object)
    def _event(self, kind: str, payload: object) -> None:
        """显示传输阶段与结论，终态含成功、失败和未确认。"""
        if not self._current_sender():
            return
        if kind in ("state", "outcome"):
            names = {"PROBE_STATUS": "探测 V2 状态", "PROBE_OTA": "检查升级条件", "BEGIN": "申请上传",
                     "WAIT_C": "等待设备接收请求", "HEADER": "发送文件信息，等待擦除", "HEADER_C": "等待开始数据",
                     "DATA": "上传中", "EOT1": "结束数据传输", "EOT2": "确认数据结束", "END_C": "等待结束批次",
                     "END_ACK": "结束包已发送，自动安装可能已启动", "QUIET": "等待设备恢复协议模式",
                     "RECOVERY": "查询实际运行版本和健康状态", "DONE": "目标版本健康运行",
                     "FAILED": "操作失败", "CANCELLED": "上传已取消", "UNCONFIRMED": "安装结果未确认"}
            self.state_label.setText(names.get(str(payload), str(payload)) if kind == "state" else str(payload))
        self.log.appendPlainText(f"{kind}: {payload}")

    @Slot(int, int)
    def _progress(self, sent: int, total: int) -> None:
        """只把已 ACK 的有效文件字节计入进度。"""
        if self._current_sender():
            self.progress_bar.setValue(int(100 * sent / max(total, 1)))

    def shutdown(self) -> None:
        """请求取消，但不伪造已停止；真正停止由父页面 Driver.stop 确认。"""
        if self._driver:
            self._driver.stop_ota()
