"""客户流量模拟的配置与限频统计区域，不操作串口。"""

from __future__ import annotations

import secrets
from pathlib import Path

from PySide6.QtCore import Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from soft_hertz_tool.devices.afdtr1024.models import DeviceVariant
from soft_hertz_tool.devices.afdtr1024.traffic import TrafficConfig


class TrafficPanel(QGroupBox):
    """仅收集参数及展示 Driver 快照，明细自动导出到本次运行目录。"""

    start_requested = Signal()
    stop_requested = Signal()

    def __init__(self, variant: DeviceVariant, parent=None):
        """构建首版简单表单；未指定的初值与计划保持一致。"""
        super().__init__("客户流量模拟", parent)
        self.run_id = ""
        self.directory = ""
        layout = QVBoxLayout(self)
        note = QLabel("客户模式：定址波束＋查询合包，不等待回复，后台分别计数。\n"
                      "定址等待模式：每个波束等待原帧回显，再继续发送；间隔从等待结束计。\n"
                      "广播：波束不应答，零间隙可与查询合并写入；线路间隔需实测。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.form_widget = QWidget()
        form = QFormLayout(self.form_widget)
        self.beam_period = self._number(10, 0.1, 60000)
        self.query_period = self._number(1000, 0.1, 600000)
        self.beam_mode = QComboBox()
        self.beam_mode.addItem("定址应答＋零间隙，不等待回复", "addressed_stream")
        self.beam_mode.addItem("指定 ID，等待回显", "addressed")
        self.beam_mode.addItem("广播，无应答", "broadcast")
        self.query_type = QComboBox()
        addresses = "0x5C + 0x5F" if variant.is_tx else "0x9C + 0x9F"
        self.query_type.addItem(f"两项（{addresses}）", "both")
        self.query_type.addItem("状态查询", "status")
        self.query_type.addItem("波束参数查询", "beam")
        self.target = QSpinBox()
        self.target.setRange(1, 127)
        self.target.setDisplayIntegerBase(16)
        self.target.setPrefix("0x")
        self.gap_mode = QComboBox()
        for label, value in (("零间隙（一次写入）", "zero"), ("指定间隔", "fixed"), ("随机间隔", "random")):
            self.gap_mode.addItem(label, value)
        self.gap = self._number(1, 0, 60000)
        self.random_min = self._number(0, 0, 60000)
        self.random_max = self._number(5, 0, 60000)
        self.duration = self._number(1, 0.001, 10080)
        self.timeout = self._number(100, 0.1, 60000)
        for label, widget in (("波束模式", self.beam_mode), ("波束周期 (ms)", self.beam_period),
                              ("查询周期 (ms)", self.query_period),
                              ("查询类型", self.query_type), ("目标 ID（波束/查询）", self.target),
                              ("波束→首查询间隔", self.gap_mode), ("指定间隔 (ms)", self.gap),
                              ("随机下限 (ms)", self.random_min), ("随机上限 (ms)", self.random_max),
                              ("运行时长 (min)", self.duration), ("回复超时 (ms)", self.timeout)):
            form.addRow(label, widget)
        layout.addWidget(self.form_widget)
        buttons = QHBoxLayout()
        self.start_button = QPushButton("开始")
        self.stop_button = QPushButton("停止")
        self.export_button = QPushButton("打开导出目录")
        self.stop_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_requested.emit)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.export_button.clicked.connect(self._open_export)
        for button in (self.start_button, self.stop_button, self.export_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.status = QLabel("未运行；明细 JSONL 与汇总 JSON 自动保存")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.gap_mode.currentIndexChanged.connect(self._update_gap_controls)
        self.beam_mode.currentIndexChanged.connect(self._update_gap_controls)
        self._update_gap_controls()

    @staticmethod
    def _number(value: float, minimum: float, maximum: float) -> QDoubleSpinBox:
        """构造带明确范围及小数精度的时间输入。"""
        widget = QDoubleSpinBox()
        widget.setDecimals(3)
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        return widget

    @Slot()
    def _update_gap_controls(self) -> None:
        """只开放当前间隔模式使用的字段。"""
        streaming = self.beam_mode.currentData() == "addressed_stream"
        if streaming:
            self.gap_mode.setCurrentIndex(0)
        self.gap_mode.setEnabled(not streaming)
        mode = self.gap_mode.currentData()
        self.gap_mode.setItemText(0, "零额外间隔（等待应答后）" if self.beam_mode.currentData() == "addressed"
                                 else "零间隙（一次写入）")
        self.gap.setEnabled(mode == "fixed")
        self.random_min.setEnabled(mode == "random")
        self.random_max.setEnabled(mode == "random")

    def config(self) -> TrafficConfig:
        """读取配置；随机种子自动生成并随运行明细持久记录。"""
        config = TrafficConfig(beam_period_ms=self.beam_period.value(), query_period_ms=self.query_period.value(),
                               query_type=self.query_type.currentData(), target_id=self.target.value(),
                               gap_mode=self.gap_mode.currentData(), gap_ms=self.gap.value(),
                               random_min_ms=self.random_min.value(), random_max_ms=self.random_max.value(),
                               duration_min=self.duration.value(), timeout_ms=self.timeout.value(),
                               seed=secrets.randbits(32), beam_mode=self.beam_mode.currentData())
        config.validate()
        return config

    def set_active(self, active: bool) -> None:
        """运行或收尾期间冻结参数，仅保留停止。"""
        self.form_widget.setEnabled(not active)
        self.start_button.setEnabled(not active)
        self.stop_button.setEnabled(active)

    def show_snapshot(self, snapshot: dict) -> None:
        """展示串口线程每 100 ms 发布的统计快照。"""
        if snapshot["run_id"] != self.run_id:
            return
        self.set_active(snapshot["active"])
        self.directory = snapshot["directory"]
        self.export_button.setEnabled(snapshot["recording_finished"])
        counts = snapshot["counts"]
        phases = {"beam": "周期波束", "gap": "查询前间隔", "wait": "等待回复", "second": "等待第二查询",
                  "writing": "写入中", "stopped": "停止"}
        reasons = {"duration": "运行时长已到", "cancelled": "用户停止", "disconnected": "串口断开",
                   "write_failure": "写入失败", "record_failure": "记录失败",
                   "tracking_capacity": "应答跟踪容量不足，统计未完整", "": ""}
        latency = snapshot.get("metrics", {}).get("reply_latency", {})
        latency_mean = latency.get("sum_ns", 0) / max(1, latency.get("count", 0)) / 1e6
        latency_max = latency.get("max_ns", 0) / 1e6
        beam_latency = snapshot.get("metrics", {}).get("beam_reply_latency", {})
        waiting = "等待波束回显" if snapshot.get("waiting_for") == "beam" and snapshot["phase"] == "wait" else phases.get(snapshot['phase'], snapshot['phase'])
        self.status.setText(
            f"{waiting} / 剩余 {snapshot['remaining_s']:.1f} s\n"
            f"收到帧 {counts.get('rx_frames_total', 0)}：波束 {counts.get('beam_reply_frames', 0)}，"
            f"状态 {counts.get('status_reply_frames', 0)}，波束参数 {counts.get('beam_query_reply_frames', 0)}\n"
            f"实际写入：波束 {counts.get('beams_written', 0)}，查询 {counts.get('queries_written', 0)}；"
            f"查询匹配 {counts.get('matched_replies', 0)}，查询超时 {counts.get('timeouts', 0)}\n"
            f"波束匹配 {counts.get('beam_matched_replies', 0)}，波束超时 {counts.get('beam_timeouts', 0)}，"
            f"波束取消 {counts.get('beam_cancelled', 0)}\n"
            f"异常回复 {counts.get('abnormal_replies', 0)}，DROP {counts.get('drops', 0)}，"
            f"跳过波束 {counts.get('skipped_beams', 0)}，跳过查询 {counts.get('skipped_queries', 0)}\n"
            f"写失败 {counts.get('write_failures', 0)}，取消 {counts.get('cancelled', 0)}，"
            f"记录丢失 {snapshot['records_lost']}\n"
            f"主机回复延迟：均值 {latency_mean:.3f} / 最大 {latency_max:.3f} ms\n"
            f"波束回显最大延迟 {beam_latency.get('max_ns', 0) / 1e6:.3f} ms\n"
            f"{reasons.get(snapshot['reason'], snapshot['reason'])} {snapshot['record_error']}"
        )
        self.status.setToolTip(self.directory)

    @Slot()
    def _open_export(self) -> None:
        """打开已完成导出的运行目录；不在 UI 线程复制大型日志。"""
        if self.directory and Path(self.directory).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.directory))
