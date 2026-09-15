"""独立 AFD01 网口测试页；不依赖 KA_RF_UNIT 设备模块。"""

from __future__ import annotations
import time
from functools import partial
from PySide6.QtCore import Signal, Slot, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
    QPushButton,
    QComboBox,
    QProgressBar,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)
from .driver import Afd01Driver
from .scan import ScanAxis, ScanGrid
from .protocol import Op, RESULTS

OP_NAMES = {
    Op.CONV_FREQ: "变频 LO/RF (MHz)",
    Op.CONV_ATT: "变频衰减 (dB)",
    Op.IF: "中频开关",
    Op.REFERENCE: "参考频率 (MHz)",
    Op.ARRAY_FREQ: "阵列频率 (MHz)",
    Op.BEAM: "波束角 (°)",
    Op.POLAR: "极化",
    Op.MODE: "阵列模式",
    Op.ARRAY_ATT: "阵列衰减 (dB)",
    Op.SIZE: "阵面大小",
    Op.ARRAY_ENABLE: "阵列开关",
    Op.PA: "TX PA",
}


class Afd01Panel(QWidget):
    """AFD01 独立顶层页面内容；控件只通过语义 Driver 提交测试请求。"""

    frame_signal = Signal(object)

    def __init__(self, parent=None) -> None:
        """创建连接、变频、阵列和只读状态控件，初始禁用设备控制。"""
        super().__init__(parent)
        self.driver = Afd01Driver(self)
        self.driver.frame_signal.connect(self.frame_signal.emit)
        self.driver.changed.connect(self.refresh)
        self.driver.status_signal.connect(self._status)
        self.driver.result_signal.connect(self._result)
        self._scan_grid = None
        self._scan_paused = False
        self._scan_index = 0
        self._scan_target_index = 0
        self._scan_request = None
        self._scan_due = 0.0
        self._scan_targets = (0,)
        self._scan_dwell = 0.2
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(25)
        self._scan_timer.timeout.connect(self._scan_tick)
        self.driver.control_finished.connect(self._scan_finished)
        self._resume = False
        self._auto_manual_pending = False
        self.controls = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        connection = QGroupBox("AFD01 · 整机 Debug 网口测试")
        row = QHBoxLayout(connection)
        self.host = QLineEdit("192.168.1.12")
        self.host.setFixedWidth(180)
        self.host.setPlaceholderText("设备 IPv4 地址")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(4004)
        self.connect_button = QPushButton("连接")
        self.connect_button.clicked.connect(self._connect)
        self.manual_button = QPushButton("切换手动模式")
        self.manual_button.clicked.connect(self._manual)
        for w in (
            QLabel("IP"),
            self.host,
            QLabel("UDP"),
            self.port,
            self.connect_button,
            self.manual_button,
        ):
            row.addWidget(w)
        layout.addWidget(connection)
        self.connection_status = QLabel("未连接；仅支持 Debug 固件，测试不接 Modem")
        row.addWidget(self.connection_status, 1)
        note = QLabel(
            "连接后自动切换手动模式。关闭页面保持设备设置；恢复自动使用 track md 0。阵列重新上线后需重设测试输出。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        body = QHBoxLayout()
        body.setSpacing(8)
        left = QVBoxLayout()
        left.setSpacing(4)
        right = QVBoxLayout()
        right.setSpacing(4)
        body.addLayout(left, 1)
        body.addLayout(right, 1)
        layout.addLayout(body)
        grids = {}
        self.inputs = {}
        for title, kind in (("变频独立控制", "conv"), ("阵列独立控制", "array")):
            group = QGroupBox(title)
            grid = QGridLayout(group)
            grid.setContentsMargins(8, 8, 8, 8)
            grid.setHorizontalSpacing(6)
            grid.setVerticalSpacing(2)
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(2, 1)
            grids[kind] = grid
            (left if kind == "conv" else right).addWidget(group)
            grid.addWidget(QLabel("操作"), 0, 0)
            for target in (0, 1):
                grid.addWidget(QLabel("TX" if target == 0 else "RX"), 0, target + 1)
            specs = (
                [
                    (
                        "LO / RF (MHz)",
                        Op.CONV_FREQ,
                        [(1, 40000, 28050, 1), (27500, 31000, 29500, 1)],
                    ),
                    ("衰减 (dB)", Op.CONV_ATT, [(0, 31.5, 0, 0.5)]),
                    ("IF", Op.IF, ["switch"]),
                ]
                if kind == "conv"
                else [
                    ("频率 (MHz)", Op.ARRAY_FREQ, [(27500, 31000, 29500, 1)]),
                    (
                        "离轴角 / 方位角 (°)",
                        Op.BEAM,
                        [(-90, 90, 0, 0.1), (-360, 360, 0, 0.1)],
                    ),
                    ("极化", Op.POLAR, [[("左旋", 0), ("右旋", 1)]]),
                    ("工作模式", Op.MODE, [[("0", 0), ("1", 1), ("2", 2)]]),
                    (
                        "公共 / 支路衰减 (dB)",
                        Op.ARRAY_ATT,
                        [(0, 8, 0, 0.5), (0, 7.5, 0, 0.5)],
                    ),
                    (
                        "阵面大小",
                        Op.SIZE,
                        [[(f"{n}×{n}", n) for n in (8, 10, 12, 14, 16)]],
                    ),
                    ("阵列开关", Op.ARRAY_ENABLE, ["switch"]),
                ]
            )
            for row_index, (label, op, fields) in enumerate(specs, 1):
                label_widget = QLabel(label)
                label_widget.setWordWrap(True)
                label_widget.setFixedWidth(110)
                grid.addWidget(label_widget, row_index, 0)
                for target in (0, 1):
                    cell = QWidget()
                    line = QHBoxLayout(cell)
                    line.setContentsMargins(0, 0, 0, 0)
                    line.setSpacing(3)
                    widgets = []
                    for index, field in enumerate(fields):
                        if field == "switch":
                            field = [("关闭", 0), ("开启", 1)]
                        if isinstance(field, list):
                            w = QComboBox()
                            for text, value in field:
                                w.addItem(text, value)
                            if op == Op.SIZE:
                                w.setCurrentIndex(4)
                        else:
                            low, high, value, step = field
                            if target == 1 and op in (Op.CONV_FREQ, Op.ARRAY_FREQ):
                                low, high, value = (
                                    (1, 40000, 18250)
                                    if op == Op.CONV_FREQ and index == 0
                                    else (17700, 21200, 19500)
                                )
                            w = QDoubleSpinBox()
                            w.setRange(low, high)
                            w.setValue(value)
                            w.setSingleStep(step)
                            w.setDecimals(0 if step == 1 else 1)
                        w.setFixedWidth(82 if isinstance(w, QComboBox) else 78)
                        line.addWidget(w)
                        widgets.append(w)
                    button = QPushButton("设置")
                    button.setFixedWidth(52)
                    button.clicked.connect(partial(self._apply, op, target, widgets))
                    line.addWidget(button)
                    line.addStretch()
                    self.controls.append((op, button))
                    self.inputs[(op, target)] = widgets
                    grid.addWidget(cell, row_index, target + 1)

        self.reference = QSpinBox()
        self.reference.setRange(10, 250)
        self.reference.setSingleStep(10)
        self.reference.setValue(100)
        ref_button = QPushButton("设置")
        ref_button.setFixedWidth(52)
        ref_button.clicked.connect(self._reference)
        self.pa = QComboBox()
        self.pa.addItem("关闭", 0)
        self.pa.addItem("开启", 1)
        pa_button = QPushButton("设置")
        pa_button.setFixedWidth(52)
        pa_button.clicked.connect(self._pa)
        self.controls.extend([(Op.REFERENCE, ref_button), (Op.PA, pa_button)])
        for kind, title, field, button in (
            ("conv", "外部参考 (MHz)", self.reference, ref_button),
            ("array", "TX PA", self.pa, pa_button),
        ):
            grid = grids[kind]
            index = grid.rowCount()
            grid.addWidget(QLabel(title), index, 0)
            cell = QWidget()
            line = QHBoxLayout(cell)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(3)
            field.setFixedWidth(82)
            line.addWidget(field)
            line.addWidget(button)
            line.addStretch()
            grid.addWidget(cell, index, 1)
        left.addWidget(self._create_scan_group())
        left.addStretch()
        right.addStretch()
        self.result = QLabel("")
        self.result.setWordWrap(True)
        right.insertWidget(1, self.result)
        self.snapshot = QTableWidget(8, 6)
        self.snapshot.setHorizontalHeaderLabels(
            ["变频状态", "TX", "RX", "阵列状态", "TX", "RX"]
        )
        self.snapshot.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.snapshot.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.snapshot.verticalHeader().hide()
        self.snapshot.verticalHeader().setDefaultSectionSize(24)
        self.snapshot.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.snapshot.setToolTip(
            "主控快照与指令发送记录；断线后旧数据失效。物理 RF 效果由仪表确认。"
        )
        for row_index, (conv, array) in enumerate(
            zip(
                (
                    "LO / RF (MHz)",
                    "衰减 (dB)",
                    "PLL 锁定",
                    "IF 请求",
                    "IF 写入有效",
                    "IF 发送值",
                    "参考 PLL",
                    "变频温度 (°C)",
                ),
                (
                    "在线",
                    "频率 (MHz)",
                    "离轴 / 方位角 (°)",
                    "极化",
                    "公共 / 支路衰减 (dB)",
                    "阵面大小",
                    "开关记录 / PA",
                    "温度 (°C)",
                ),
            )
        ):
            for col, value in enumerate((conv, "—", "—", array, "—", "—")):
                self.snapshot.setItem(row_index, col, QTableWidgetItem(value))
        self.snapshot.setSpan(7, 1, 1, 2)
        self.snapshot.setFixedHeight(220)
        layout.addWidget(self.snapshot)
        layout.addStretch()
        self.refresh()

    @Slot()
    def _connect(self) -> None:
        """用户连接或断开；手动断开后切换 Tab 不会自动重连。"""
        self._resume = False
        if self.driver.socket:
            self.driver.close()
            return
        try:
            self.driver.connect_device(self.host.text().strip(), self.port.value())
            self._auto_manual_pending = True
        except (ValueError, OSError) as exc:
            self._result(str(exc))

    @Slot()
    def _manual(self) -> None:
        """请求固件进入现有 Tracking 手动模式。"""
        self._send(Op.MANUAL)

    @Slot()
    def _reference(self) -> None:
        """发送 MHz 单位的临时参考频率，不保存参数。"""
        self._send(Op.REFERENCE, 0, self.reference.value())

    @Slot()
    def _pa(self) -> None:
        """发送独立 TX PA 开关请求。"""
        self._send(Op.PA, 0, self.pa.currentData())

    @Slot()
    def _apply(self, op: Op, target: int, widgets: list, checked: bool = False) -> None:
        """把当前控件值转换为所选通道的语义请求，不拼协议帧。"""
        values = [
            w.currentData() if isinstance(w, QComboBox) else w.value() for w in widgets
        ]
        self._send(op, target, *values)

    def _send(
        self, op: Op, target: int = 0, a: float = 0, b: float = 0, c: float = 0
    ) -> None:
        """提交一次控制并展示参数或网络错误；不自动修正和重试。"""
        if self._scan_grid is not None:
            self._result("请先停止扫描再修改其他设置")
            return
        try:
            self.driver.control(op, target, a, b, c)
        except (ValueError, OSError) as exc:
            self._result(str(exc))

    @Slot(str)
    def _result(self, text: str) -> None:
        """显示异常和模式反馈，省略发送成功及扫描中的接受提示。"""
        if text == RESULTS[1] or (
            self._scan_grid is not None and text == "请求已接受，等待 owner 执行结果"
        ):
            text = ""
        self.result.setText(text)

    @Slot()
    def refresh(self) -> None:
        """根据能力、模式、新鲜度和在途请求更新控件门禁。"""
        d = self.driver
        if not d.socket:
            self._auto_manual_pending = False
        if self._auto_manual_pending and d.fresh:
            self._auto_manual_pending = False
            if not d.manual:
                self._manual()
        if self._scan_grid is not None:
            if d.socket is None:
                self._stop_scan("扫描停止：连接已断开")
            elif d.fresh and not d.manual:
                self._stop_scan("扫描停止：已退出手动模式")
            elif d.fresh and not d.latest.get("capabilities", 0) & (1 << Op.BEAM):
                self._stop_scan("扫描停止：固件不支持波束控制")
        scanning = self._scan_grid is not None
        self.connect_button.setText("断开" if d.socket else "连接")
        self.host.setEnabled(d.socket is None)
        self.port.setEnabled(d.socket is None)
        if not d.socket:
            text = "未连接；旧状态失效"
        elif d.fresh:
            text = f"{d.latest['model']} · {'手动模式' if d.manual else '尚未进入手动模式'} · 最近响应 {time.monotonic()-d.last_response:.1f}s"
        elif time.monotonic() - d.opened < 3:
            text = "等待设备测试能力响应…"
        else:
            text = "测试能力未确认或状态失效；请检查网络及 Debug 固件，Release/旧固件不可控制"
        self.connection_status.setText(text)
        self.manual_button.setEnabled(
            not scanning
            and d.fresh
            and d.pending is None
            and not d.manual
            and bool(d.latest.get("capabilities", 0) & (1 << Op.MANUAL))
        )
        for op, button in self.controls:
            button.setEnabled(
                not scanning
                and d.can_control
                and bool(d.latest.get("capabilities", 0) & (1 << op))
            )
        self.snapshot.setEnabled(d.fresh)
        self.scan_start.setEnabled(
            not scanning
            and d.can_control
            and bool(d.latest.get("capabilities", 0) & (1 << Op.BEAM))
        )
        self.scan_pause.setEnabled(scanning)
        self.scan_stop.setEnabled(scanning)
        self.scan_pause.setText("继续" if self._scan_paused else "暂停")
        for widget in self._scan_inputs:
            widget.setEnabled(not scanning)

    @Slot(dict)
    def _status(self, s: dict) -> None:
        """按字段有效位显示主控快照，保持编辑框内尚未发送的输入。"""
        c = s["converter"]
        flags = c["flags"]
        for target, prefix in enumerate(("tx", "rx")):
            values = ["未知"] * 8
            if flags & 1:
                values = [
                    f"{c[prefix + '_lo']:g} / {c[prefix + '_rf']:g}",
                    f"{c[prefix + '_att']:g}",
                    "锁定" if flags & (8 << target) else "未锁定",
                    "开启" if flags & (64 << target) else "关闭",
                    "有效" if flags & (256 << target) else "无效",
                    (
                        ("开启" if flags & (1024 << target) else "关闭")
                        if flags & (256 << target)
                        else "未知"
                    ),
                    "锁定" if flags & 4 else "未锁定",
                    f"{c['temperature']:g}" if flags & 32 else "未知",
                ]
                if not s["capabilities"] & (1 << Op.IF):
                    values[3:6] = ["不支持"] * 3
            for row, value in enumerate(values):
                if row == 7 and target == 1:
                    continue
                self.snapshot.item(row, target + 1).setText(value)
            a = s["arrays"][target]
            f = a["flags"]
            values = ["未初始化"] + ["未知"] * 7
            if f & 1:
                pa = ("开启" if f & 8 else "关闭") if f & 32 else "未知"
                values = [
                    "在线" if f & 2 else "离线",
                    f"{a['frequency']:g}",
                    f"{a['theta']:.1f} / {a['phi']:.1f}",
                    {0: "左旋", 1: "右旋"}.get(a["polar"], str(a["polar"])),
                    f"{a['common']:g} / {a['branch']:g}",
                    f"{a['size']}×{a['size']}",
                    f"{'开启' if f & 4 else '关闭'} / {pa}",
                    f"{a['temperature']:g}" if f & 16 else "未知",
                ]
            for row, value in enumerate(values):
                self.snapshot.item(row, target + 4).setText(value)

    def activate(self) -> None:
        """仅恢复因切换 Tab 关闭的连接，重新查询且不重放控制。"""
        if self._resume:
            self._resume = False
            self._connect()

    def deactivate(self) -> bool:
        """记录是否需恢复连接并关闭 socket，可重复调用。"""
        self._stop_scan("扫描停止：离开 AFD01 页面")
        self._resume = self._resume or self.driver.socket is not None
        return self.driver.close()

    def shutdown(self) -> bool:
        """幂等关闭 socket，清除自动恢复连接意图。"""
        self._stop_scan("扫描停止：页面关闭")
        self._resume = False
        return self.driver.close()

    def _create_scan_group(self) -> QGroupBox:
        """创建独立扫描参数区；长状态文字独占一行并自动换行。"""
        group = QGroupBox("阵列波束扫描")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(3)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        layout.addLayout(grid)
        for col, title in enumerate(("角度 (°)", "起点", "终点", "步长")):
            grid.addWidget(QLabel(title), 0, col)
        grid.setColumnStretch(4, 1)
        self.scan_axes = []
        self._scan_inputs = []
        for row, (name, limit, defaults) in enumerate(
            (("θ 离轴角", 90, (0, 30, 5)), ("φ 方位角", 360, (0, 90, 10)))
        ):
            grid.addWidget(QLabel(name), row + 1, 0)
            widgets = []
            for col, value in enumerate(defaults):
                spin = QDoubleSpinBox()
                spin.setFixedWidth(78)
                spin.setDecimals(1)
                spin.setRange(
                    0.1 if col == 2 else -limit, 2 * limit if col == 2 else limit
                )
                spin.setValue(value)
                spin.setSingleStep(0.1 if col == 2 else 1)
                spin.setKeyboardTracking(False)
                spin.setToolTip(
                    f"步长：0.1～{2 * limit}°"
                    if col == 2
                    else f"范围：−{limit}～{limit}°；全选后可替换数值"
                )
                grid.addWidget(spin, row + 1, col + 1)
                widgets.append(spin)
            self.scan_axes.append(widgets)
            self._scan_inputs.extend(widgets)
        self.scan_target = QComboBox()
        for label, targets in (
            ("TX", (0,)),
            ("RX", (1,)),
            ("TX+RX（依次发送）", (0, 1)),
        ):
            self.scan_target.addItem(label, targets)
        self.scan_interval = QSpinBox()
        self.scan_interval.setRange(50, 60000)
        self.scan_interval.setValue(200)
        self.scan_interval.setFixedWidth(82)
        self.scan_target.setFixedWidth(170)
        options = QHBoxLayout()
        options.addWidget(QLabel("目标"))
        options.addWidget(self.scan_target)
        options.addWidget(QLabel("扫描间隔（ms）"))
        options.addWidget(self.scan_interval)
        options.addStretch()
        layout.addLayout(options)
        self._scan_inputs.extend((self.scan_target, self.scan_interval))
        note = QLabel(
            "使用各阵列当前频率；一轴起终点相同可做单轴扫描。停止保持最后输出，已发送的指令仍可能执行。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QHBoxLayout()
        layout.addLayout(buttons)
        self.scan_start = QPushButton("开始")
        self.scan_start.clicked.connect(self._start_scan)
        self.scan_pause = QPushButton("暂停")
        self.scan_pause.clicked.connect(self._pause_scan)
        self.scan_stop = QPushButton("停止")
        self.scan_stop.clicked.connect(self._scan_stop_clicked)
        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 1)
        for w in (self.scan_start, self.scan_pause, self.scan_stop, self.scan_progress):
            buttons.addWidget(w)
        self.scan_status = QLabel("未开始")
        self.scan_status.setWordWrap(True)
        self.scan_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.scan_status)
        return group

    def _scan_device_ready(self) -> bool:
        """确认新鲜手动状态、所选阵列在线且当前频率有效。"""
        d = self.driver
        if not d.manual or not d.latest.get("capabilities", 0) & (1 << Op.BEAM):
            return False
        arrays = d.latest.get("arrays", [])
        return len(arrays) == 2 and all(
            arrays[t]["flags"] & 3 == 3 and arrays[t]["frequency"] > 0
            for t in self._scan_targets
        )

    @Slot()
    def _start_scan(self) -> None:
        """冻结参数并开始一次扫描；当前无控制在途且阵列已在线才启动。"""
        if self._scan_grid is not None or not self.driver.can_control:
            return
        try:
            theta = ScanAxis.degrees(*(w.value() for w in self.scan_axes[0]), 90)
            phi = ScanAxis.degrees(*(w.value() for w in self.scan_axes[1]), 360)
            self._scan_targets = tuple(self.scan_target.currentData())
            if not self._scan_device_ready():
                raise ValueError("所选阵列需在线且频率有效")
        except ValueError as exc:
            self.scan_status.setText(str(exc))
            return
        self._scan_grid = ScanGrid(theta, phi)
        self._scan_index = 0
        self._scan_target_index = 0
        self._scan_request = None
        self._scan_paused = False
        self._scan_due = 0
        self._scan_dwell = self.scan_interval.value() / 1000
        self.scan_progress.setRange(0, self._scan_grid.count)
        self.scan_progress.setValue(0)
        self.driver.set_scan_polling(True)
        self._scan_timer.start()
        self.refresh()
        self._scan_tick()

    @Slot()
    def _scan_tick(self) -> None:
        """有序发送每点每个目标；等待确认与停留期间均不提前发送。"""
        grid = self._scan_grid
        if grid is None:
            return
        self.refresh()
        if self._scan_grid is None or self._scan_paused:
            return
        if not self._scan_device_ready():
            self._scan_message("等待恢复", current=True)
            return
        if (
            self._scan_paused
            or self._scan_request is not None
            or time.monotonic() < self._scan_due
        ):
            return
        if self._scan_index >= grid.count:
            self._stop_scan("扫描完成")
            return
        theta, phi = grid.point(self._scan_index)
        target = self._scan_targets[self._scan_target_index]
        try:
            self._scan_request = self.driver.control(Op.BEAM, target, theta, phi)
        except OSError:
            self._retry_scan_point()
            return
        except ValueError as exc:
            self._stop_scan("扫描停止：" + str(exc))
            return
        self.scan_status.setText(
            f"完成 {self._scan_index}/{grid.count} 点 | θ={theta:g}° φ={phi:g}° | {'TX' if target==0 else 'RX'}"
        )

    @Slot(object)
    def _scan_finished(self, result: dict) -> None:
        """只处理当前扫描请求的匹配结果；ACCEPTED 不会触发此完成信号。"""
        if (
            self._scan_grid is None
            or result["id"] != self._scan_request
            or result["operation"] != Op.BEAM
        ):
            return
        if result["result"] in (None, 3, 6, 7):
            self._retry_scan_point()
            return
        if result["result"] != 1:
            self._stop_scan(
                "扫描停止：" + RESULTS.get(result["result"], "超时，执行结果未知")
            )
            return
        self._scan_request = None
        self._scan_target_index += 1
        if self._scan_target_index == len(self._scan_targets):
            self._scan_target_index = 0
            self._scan_index += 1
            self.scan_progress.setValue(self._scan_index)
            self._scan_due = time.monotonic() + self._scan_dwell
        self._scan_message("已暂停" if self._scan_paused else "")

    def _retry_scan_point(self) -> None:
        """保留当前点与目标，至少一秒后重试；暂停期间由扫描节拍禁止发送。"""
        self._scan_message(
            "已暂停" if self._scan_paused else "等待恢复／重试当前点", current=True
        )
        self._scan_request = None
        self._scan_due = time.monotonic() + 1.0

    @Slot()
    def _pause_scan(self) -> None:
        """暂停不取消已发送请求；继续时完成点重新停留完整间隔。"""
        if self._scan_grid is None:
            return
        self._scan_paused = not self._scan_paused
        if not self._scan_paused and self._scan_request is None:
            self._scan_due = max(
                self._scan_due,
                time.monotonic()
                + (
                    self._scan_dwell
                    if self._scan_target_index == 0 and self._scan_index > 0
                    else 0
                ),
            )
        self._scan_message(
            "暂停中，已发送请求仍会结算" if self._scan_paused else "继续扫描"
        )
        self.refresh()

    @Slot()
    def _scan_stop_clicked(self) -> None:
        """停止后续发送，设备保留最后输出。"""
        self._stop_scan("扫描已停止；保持最后输出，已发送请求仍可能执行")

    def _stop_scan(self, text: str) -> None:
        """结束本次扫描，不清除 Driver 在途请求，不发送复位或关闭指令。"""
        if self._scan_grid is None:
            return
        self._scan_message(text)
        self._scan_timer.stop()
        self._scan_grid = None
        self._scan_request = None
        self._scan_paused = False
        self.driver.set_scan_polling(False)
        self.refresh()

    def _scan_message(self, text: str, current: bool = False) -> None:
        """在等待、暂停和结束时保留当前点角度、目标和完成进度。"""
        grid = self._scan_grid
        if grid is None:
            return
        index = self._scan_index
        if (
            not current
            and self._scan_request is None
            and self._scan_target_index == 0
            and index > 0
        ):
            index -= 1
        theta, phi = grid.point(min(index, grid.count - 1))
        target = "+".join("TX" if t == 0 else "RX" for t in self._scan_targets)
        suffix = f" | {text}" if text else ""
        self.scan_status.setText(
            f"完成 {self._scan_index}/{grid.count} 点 | θ={theta:g}° φ={phi:g}° | {target}{suffix}"
        )
