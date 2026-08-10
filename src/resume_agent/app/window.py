from __future__ import annotations

import asyncio
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from resume_agent.audit.coverage import audit_run
from resume_agent.config import APP_NAME, WorkspacePaths, default_config, load_api_key, save_api_key
from resume_agent.criteria.compiler import compile_criteria
from resume_agent.domain.models import (
    AnalysisResult,
    Conclusion,
    Criterion,
    CriterionKind,
    ProgressEvent,
    RunConfig,
    ScanResult,
)
from resume_agent.llm.deepseek import DeepSeekClient
from resume_agent.materials.copying import copy_candidate_packages
from resume_agent.reporting.excel import export_excel
from resume_agent.safety import escape_rich_text
from resume_agent.scanning.scanner import default_output_dir, scan_resume_root
from resume_agent.storage.database import Database
from resume_agent.workers.engine import ScreeningEngine, effective_worker_count

STYLE = """
QWidget { color: #183247; background: #F6F8F9; font-size: 13px; }
QMainWindow { background: #F6F8F9; }
QFrame#Sidebar { background: #132D3B; border: none; }
QFrame#Sidebar QLabel { background: transparent; }
QLabel#Brand { color: white; font-size: 20px; font-weight: 700; padding: 4px 0; }
QLabel#BrandSub { color: #9FB7C2; font-size: 11px; }
QListWidget#Navigation { background: transparent; color: #B9CBD3; border: none; outline: 0; }
QListWidget#Navigation::item { height: 42px; padding-left: 14px; border-radius: 6px; }
QListWidget#Navigation::item:selected { background: #1E5360; color: white; }
QListWidget#Navigation::item:hover { background: #193E49; }
QLabel#PageTitle { font-size: 24px; font-weight: 700; color: #102D3C; }
QLabel#PageSub { color: #627781; font-size: 12px; }
QLabel#Metric { font-size: 25px; font-weight: 700; color: #0D6B6F; }
QLabel#Section { font-size: 15px; font-weight: 700; color: #193746; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QTableWidget, QTextBrowser {
  background: white; border: 1px solid #D8E0E3; border-radius: 6px; padding: 7px;
  selection-background-color: #CFE8E5; selection-color: #102D3C;
}
QLineEdit:focus, QPlainTextEdit:focus,
QComboBox:focus, QSpinBox:focus { border: 1px solid #0D7A7F; }
QPushButton { background: white; border: 1px solid #CDD9DD; border-radius: 6px; padding: 8px 14px; }
QPushButton:hover { background: #EDF4F4; border-color: #91B8B9; }
QPushButton#Primary { background: #0D7478; color: white; border: none; font-weight: 600; }
QPushButton#Primary:hover { background: #0A6367; }
QPushButton#Danger { color: #A33C36; }
QPushButton:disabled { background: #E8ECEE; color: #9AA8AE; }
QHeaderView::section { background: #EDF2F3; color: #405963; padding: 8px;
  border: none; border-bottom: 1px solid #D8E0E3; font-weight: 600; }
QTableWidget { gridline-color: #E8EDEF; border-radius: 6px; }
QProgressBar { border: none; background: #DEE7E9; border-radius: 5px;
  height: 10px; text-align: center; }
QProgressBar::chunk { background: #0D7478; border-radius: 5px; }
QSplitter::handle { background: #DDE5E7; width: 1px; }
"""


class ScanThread(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def run(self) -> None:
        try:
            self.completed.emit(scan_resume_root(self.path))
        except Exception as exc:
            self.failed.emit(str(exc))


class CriteriaThread(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, jd: str, requirements: str, config: RunConfig, api_key: str | None):
        super().__init__()
        self.jd = jd
        self.requirements = requirements
        self.config = config
        self.api_key = api_key

    def run(self) -> None:
        try:
            client = DeepSeekClient(self.api_key, self.config) if self.api_key else None
            result = asyncio.run(compile_criteria(self.jd, self.requirements, client))
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class EngineThread(QThread):
    progress_event = Signal(object)
    completed = Signal(str, object)
    failed = Signal(str)

    def __init__(
        self,
        database: Database,
        config: RunConfig,
        api_key: str | None,
        scan: ScanResult,
        criteria: list[Criterion],
        jd: str,
        requirements: str,
        output_root: Path,
    ):
        super().__init__()
        self.database = database
        self.config = config
        self.api_key = api_key
        self.scan = scan
        self.criteria = criteria
        self.jd = jd
        self.requirements = requirements
        self.output_root = output_root
        self.loop: asyncio.AbstractEventLoop | None = None
        self.engine: ScreeningEngine | None = None

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.engine = ScreeningEngine(
                self.database,
                self.config,
                self.api_key,
                progress=lambda event: self.progress_event.emit(event),
            )
            run_id, results = self.loop.run_until_complete(
                self.engine.run(
                    self.scan,
                    self.criteria,
                    self.jd,
                    self.requirements,
                    self.output_root,
                )
            )
            self.completed.emit(run_id, results)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}")
        finally:
            self.loop.close()

    def _call(self, method: str) -> None:
        if self.loop and self.engine:
            self.loop.call_soon_threadsafe(getattr(self.engine, method))

    def pause(self) -> None:
        self._call("pause")

    def resume(self) -> None:
        self._call("resume")

    def cancel(self) -> None:
        self._call("cancel")


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget, config: RunConfig):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("留空表示保持现有系统凭据")
        self.model = QLineEdit(config.model)
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 16)
        self.concurrency.setValue(config.worker_count)
        self.redact = QCheckBox("发送前脱敏姓名、联系方式、地址和身份证号")
        self.redact.setChecked(config.redact_pii)
        form.addRow("DeepSeek API Key", self.key)
        form.addRow("分析模型", self.model)
        form.addRow("并行 Worker", self.concurrency)
        form.addRow("隐私", self.redact)
        layout.addLayout(form)
        note = QLabel("密钥只写入系统钥匙串，不保存到项目、数据库或日志。")
        note.setObjectName("PageSub")
        layout.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply(self, config: RunConfig) -> RunConfig:
        if self.key.text().strip():
            save_api_key(self.key.text())
        count = self.concurrency.value()
        return config.model_copy(
            update={
                "model": self.model.text().strip() or config.model,
                "worker_count": count,
                "extraction_concurrency": count,
                "analysis_concurrency": count,
                "redact_pii": self.redact.isChecked(),
            }
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 900)
        self.setMinimumSize(QSize(1120, 720))
        self.setStyleSheet(STYLE)
        self.settings = QSettings()
        self.config = default_config()
        self.scan_result: ScanResult | None = None
        self.criteria: list[Criterion] = []
        self.analyses: list[AnalysisResult] = []
        self.run_id = ""
        self.workspace: WorkspacePaths | None = None
        self.database: Database | None = None
        self.scan_thread: ScanThread | None = None
        self.criteria_thread: CriteriaThread | None = None
        self.engine_thread: EngineThread | None = None
        self.worker_labels: list[QLabel] = []
        self._build_ui()
        self._restore_settings()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        horizontal = QHBoxLayout(root)
        horizontal.setContentsMargins(0, 0, 0, 0)
        horizontal.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(22, 26, 18, 18)
        brand = QLabel("RESUME / AI")
        brand.setObjectName("Brand")
        sub = QLabel("简历筛选工作台")
        sub.setObjectName("BrandSub")
        side_layout.addWidget(brand)
        side_layout.addWidget(sub)
        side_layout.addSpacing(28)
        self.navigation = QListWidget()
        self.navigation.setObjectName("Navigation")
        for text in ("01  任务配置", "02  筛选条件", "03  处理进度", "04  候选人结果"):
            self.navigation.addItem(QListWidgetItem(text))
        self.navigation.currentRowChanged.connect(self._navigate)
        side_layout.addWidget(self.navigation)
        side_layout.addStretch()
        settings_button = QPushButton("设置")
        settings_button.clicked.connect(self._open_settings)
        side_layout.addWidget(settings_button)
        self.api_status = QLabel()
        self.api_status.setObjectName("BrandSub")
        side_layout.addWidget(self.api_status)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_task_page())
        self.pages.addWidget(self._build_criteria_page())
        self.pages.addWidget(self._build_progress_page())
        self.pages.addWidget(self._build_results_page())
        horizontal.addWidget(sidebar)
        horizontal.addWidget(self.pages, 1)
        self.navigation.setCurrentRow(0)
        self._update_api_status()

    def _page_shell(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 28, 34, 28)
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("PageSub")
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        layout.addSpacing(22)
        return page, layout

    def _path_row(self, line_edit: QLineEdit, callback) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit, 1)
        button = QPushButton("选择…")
        button.clicked.connect(callback)
        layout.addWidget(button)
        return widget

    def _build_task_page(self) -> QWidget:
        page, layout = self._page_shell(
            "新建筛选任务", "每个一级子目录视为一名候选人，目录中的全部材料将被登记。"
        )
        form = QFormLayout()
        form.setVerticalSpacing(14)
        self.resume_root = QLineEdit()
        self.resume_root.setPlaceholderText("选择包含候选人子目录的根目录")
        self.output_root = QLineEdit()
        self.output_root.setPlaceholderText("数据库、缓存、Excel 和整理材料的保存位置")
        form.addRow("简历根目录", self._path_row(self.resume_root, self._choose_resume_root))
        form.addRow("输出目录", self._path_row(self.output_root, self._choose_output_root))
        layout.addLayout(form)
        scan_line = QHBoxLayout()
        self.scan_button = QPushButton("扫描目录")
        self.scan_button.clicked.connect(self._scan)
        self.scan_summary = QLabel("尚未扫描")
        self.scan_summary.setObjectName("PageSub")
        scan_line.addWidget(self.scan_button)
        scan_line.addWidget(self.scan_summary)
        scan_line.addStretch()
        layout.addLayout(scan_line)
        layout.addSpacing(8)
        jd_label = QLabel("岗位 JD")
        jd_label.setObjectName("Section")
        layout.addWidget(jd_label)
        self.jd = QPlainTextEdit()
        self.jd.setPlaceholderText("粘贴岗位职责、任职要求、专业技能和加分项…")
        self.jd.setMinimumHeight(190)
        layout.addWidget(self.jd, 1)
        req_label = QLabel("补充筛选要求")
        req_label.setObjectName("Section")
        layout.addWidget(req_label)
        self.requirements = QPlainTextEdit()
        self.requirements.setPlaceholderText(
            "例如：本科院校需按指定名单核验；优先具有药物研发项目经验"
        )
        self.requirements.setMaximumHeight(110)
        layout.addWidget(self.requirements)
        actions = QHBoxLayout()
        privacy = QLabel("原文件仅在本机处理；发送模型前默认脱敏常见个人信息。")
        privacy.setObjectName("PageSub")
        self.compile_button = QPushButton("解析筛选条件 →")
        self.compile_button.setObjectName("Primary")
        self.compile_button.clicked.connect(self._compile_criteria)
        actions.addWidget(privacy)
        actions.addStretch()
        actions.addWidget(self.compile_button)
        layout.addLayout(actions)
        return page

    def _build_criteria_page(self) -> QWidget:
        page, layout = self._page_shell(
            "确认筛选条件", "先确认口径和权重，再启动 8 路处理；表格可直接编辑。"
        )
        toolbar = QHBoxLayout()
        add = QPushButton("新增条件")
        add.clicked.connect(lambda: self._append_criterion_row(None))
        remove = QPushButton("删除选中")
        remove.clicked.connect(self._remove_criterion_rows)
        toolbar.addWidget(add)
        toolbar.addWidget(remove)
        toolbar.addStretch()
        self.criteria_count = QLabel("0 项")
        self.criteria_count.setObjectName("PageSub")
        toolbar.addWidget(self.criteria_count)
        layout.addLayout(toolbar)
        self.criteria_table = QTableWidget(0, 6)
        self.criteria_table.setHorizontalHeaderLabels(
            ["启用", "名称", "定义/证据口径", "类型", "权重", "需外部核验"]
        )
        self.criteria_table.verticalHeader().setVisible(False)
        header = self.criteria_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.criteria_table, 1)
        actions = QHBoxLayout()
        warning = QLabel("排名、985/211、双一流等条件若无可信名单，将保持“不确定”。")
        warning.setObjectName("PageSub")
        self.start_button = QPushButton("开始批量筛选 →")
        self.start_button.setObjectName("Primary")
        self.start_button.clicked.connect(self._start_screening)
        actions.addWidget(warning)
        actions.addStretch()
        actions.addWidget(self.start_button)
        layout.addLayout(actions)
        return page

    def _build_progress_page(self) -> QWidget:
        page, layout = self._page_shell(
            "处理进度", "Worker 动态领取候选人；同一候选人的材料先去重和分类，再合并分析。"
        )
        metrics = QHBoxLayout()
        self.progress_metric = QLabel("0 / 0")
        self.progress_metric.setObjectName("Metric")
        self.progress_state = QLabel("等待启动")
        self.progress_state.setObjectName("PageSub")
        metric_block = QVBoxLayout()
        metric_block.addWidget(self.progress_metric)
        metric_block.addWidget(self.progress_state)
        metrics.addLayout(metric_block)
        metrics.addStretch()
        self.pause_button = QPushButton("暂停")
        self.pause_button.clicked.connect(self._toggle_pause)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("Danger")
        self.cancel_button.clicked.connect(self._cancel)
        self.pause_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        metrics.addWidget(self.pause_button)
        metrics.addWidget(self.cancel_button)
        layout.addLayout(metrics)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        layout.addSpacing(12)
        workers_title = QLabel("Worker 状态")
        workers_title.setObjectName("Section")
        layout.addWidget(workers_title)
        worker_frame = QFrame()
        self.worker_layout = QVBoxLayout(worker_frame)
        self.worker_layout.setContentsMargins(0, 0, 0, 0)
        self._reset_worker_labels(self.config.worker_count)
        layout.addWidget(worker_frame)
        log_title = QLabel("运行事件")
        log_title.setObjectName("Section")
        layout.addWidget(log_title)
        self.event_log = QPlainTextEdit()
        self.event_log.setReadOnly(True)
        self.event_log.setMaximumBlockCount(300)
        layout.addWidget(self.event_log, 1)
        return page

    def _reset_worker_labels(self, count: int) -> None:
        while self.worker_layout.count():
            item = self.worker_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.worker_labels.clear()
        for index in range(count):
            label = QLabel(f"Worker {index + 1}  ·  空闲")
            label.setMinimumHeight(28)
            if index % 2 == 0:
                label.setStyleSheet("background:#EEF3F4; padding:6px; border-radius:4px;")
            else:
                label.setStyleSheet("padding:6px;")
            self.worker_labels.append(label)
            self.worker_layout.addWidget(label)

    def _build_results_page(self) -> QWidget:
        page, layout = self._page_shell(
            "候选人结果", "按分数和状态筛选，所有结论均可展开查看材料证据。"
        )
        toolbar = QHBoxLayout()
        self.result_search = QLineEdit()
        self.result_search.setPlaceholderText("搜索姓名、公司或技能")
        self.result_search.textChanged.connect(self._apply_result_filter)
        self.min_score = QSpinBox()
        self.min_score.setRange(0, 100)
        self.min_score.setPrefix("最低分 ")
        self.min_score.valueChanged.connect(self._apply_result_filter)
        self.export_button = QPushButton("导出 Excel")
        self.export_button.clicked.connect(self._export)
        self.copy_button = QPushButton("整理勾选材料")
        self.copy_button.setObjectName("Primary")
        self.copy_button.clicked.connect(self._copy_selected)
        toolbar.addWidget(self.result_search, 1)
        toolbar.addWidget(self.min_score)
        toolbar.addWidget(self.export_button)
        toolbar.addWidget(self.copy_button)
        layout.addLayout(toolbar)
        splitter = QSplitter()
        self.results_table = QTableWidget(0, 12)
        self.results_table.setHorizontalHeaderLabels(
            [
                "选择",
                "排名",
                "姓名",
                "分数",
                "建议",
                "学历",
                "最近公司",
                "不确定",
                "候选人ID",
                "HR状态",
                "负责人",
                "HR备注",
            ]
        )
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setColumnHidden(8, True)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.results_table.setSortingEnabled(True)
        self.results_table.itemSelectionChanged.connect(self._show_evidence)
        self.results_table.itemChanged.connect(self._manual_field_changed)
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in {
            0: 50,
            1: 52,
            2: 110,
            3: 64,
            4: 76,
            5: 82,
            6: 130,
            7: 74,
            9: 96,
            10: 86,
            11: 150,
        }.items():
            self.results_table.setColumnWidth(column, width)
        self.evidence = QTextBrowser()
        self.evidence.setMinimumWidth(360)
        self.evidence.setOpenExternalLinks(False)
        self.evidence.setOpenLinks(False)
        splitter.addWidget(self.results_table)
        splitter.addWidget(self.evidence)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        self.result_summary = QLabel("尚无结果")
        self.result_summary.setObjectName("PageSub")
        layout.addWidget(self.result_summary)
        return page

    def _navigate(self, index: int) -> None:
        if index >= 0:
            self.pages.setCurrentIndex(index)

    def _choose_resume_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择简历根目录", self.resume_root.text())
        if path:
            self.resume_root.setText(path)
            if not self.output_root.text():
                self.output_root.setText(str(default_output_dir(Path(path))))
            self.scan_result = None
            self.scan_summary.setText("目录已更改，请重新扫描")

    def _choose_output_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_root.text())
        if path:
            self.output_root.setText(path)

    def _scan(self) -> None:
        path = Path(self.resume_root.text().strip()).expanduser()
        self.scan_button.setEnabled(False)
        self.scan_summary.setText("正在计算文件清单与哈希…")
        self.scan_thread = ScanThread(path)
        self.scan_thread.completed.connect(self._scan_completed)
        self.scan_thread.failed.connect(self._scan_failed)
        self.scan_thread.start()

    def _scan_completed(self, scan: ScanResult) -> None:
        self.scan_result = scan
        self.scan_button.setEnabled(True)
        supported = sum(
            file.absolute_path.suffix.lower()
            in {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
            for candidate in scan.candidates
            for file in candidate.files
        )
        self.scan_summary.setText(
            f"{len(scan.candidates)} 名候选人 · {scan.file_count} 个文件 · {supported} 个可提取 · "
            f"{len(scan.unassigned_files)} 个未归属"
        )
        if scan.unassigned_files:
            QMessageBox.warning(
                self,
                "发现未归属文件",
                f"根目录有 {len(scan.unassigned_files)} 个文件不在候选人子目录中。"
                "它们不会自动归给任何候选人，请先整理目录。",
            )

    def _scan_failed(self, message: str) -> None:
        self.scan_button.setEnabled(True)
        self.scan_summary.setText("扫描失败")
        QMessageBox.critical(self, "扫描失败", message)

    def _compile_criteria(self) -> None:
        jd = self.jd.toPlainText().strip()
        requirements = self.requirements.toPlainText().strip()
        if not jd and not requirements:
            QMessageBox.warning(self, "缺少岗位要求", "请先粘贴 JD 或补充筛选要求。")
            return
        self.compile_button.setEnabled(False)
        self.compile_button.setText("正在解析…")
        self.criteria_thread = CriteriaThread(jd, requirements, self.config, load_api_key())
        self.criteria_thread.completed.connect(self._criteria_completed)
        self.criteria_thread.failed.connect(self._criteria_failed)
        self.criteria_thread.start()

    def _criteria_completed(self, criteria: list[Criterion]) -> None:
        self.criteria = criteria
        self.criteria_table.setRowCount(0)
        for item in criteria:
            self._append_criterion_row(item)
        self.compile_button.setEnabled(True)
        self.compile_button.setText("重新解析筛选条件 →")
        self.navigation.setCurrentRow(1)

    def _criteria_failed(self, message: str) -> None:
        self.compile_button.setEnabled(True)
        self.compile_button.setText("解析筛选条件 →")
        QMessageBox.critical(self, "条件解析失败", message)

    def _append_criterion_row(self, criterion: Criterion | None) -> None:
        row = self.criteria_table.rowCount()
        self.criteria_table.insertRow(row)
        enabled = QTableWidgetItem()
        enabled.setFlags(enabled.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        enabled.setCheckState(
            Qt.CheckState.Checked
            if criterion is None or criterion.enabled
            else Qt.CheckState.Unchecked
        )
        enabled.setData(Qt.ItemDataRole.UserRole, criterion.criterion_id if criterion else "")
        self.criteria_table.setItem(row, 0, enabled)
        self.criteria_table.setItem(
            row, 1, QTableWidgetItem(criterion.name if criterion else "新条件")
        )
        self.criteria_table.setItem(
            row, 2, QTableWidgetItem(criterion.definition if criterion else "请填写可核验定义")
        )
        kind = QComboBox()
        kind.addItem("硬性", CriterionKind.REQUIRED)
        kind.addItem("评分", CriterionKind.SCORED)
        kind.addItem("加分", CriterionKind.BONUS)
        if criterion:
            kind.setCurrentIndex(
                [CriterionKind.REQUIRED, CriterionKind.SCORED, CriterionKind.BONUS].index(
                    criterion.kind
                )
            )
        else:
            kind.setCurrentIndex(1)
        self.criteria_table.setCellWidget(row, 3, kind)
        weight = QSpinBox()
        weight.setRange(0, 100)
        weight.setValue(int(criterion.weight if criterion else 10))
        self.criteria_table.setCellWidget(row, 4, weight)
        external = QTableWidgetItem()
        external.setFlags(external.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        external.setCheckState(
            Qt.CheckState.Checked
            if criterion and criterion.requires_external_fact
            else Qt.CheckState.Unchecked
        )
        self.criteria_table.setItem(row, 5, external)
        self.criteria_count.setText(f"{self.criteria_table.rowCount()} 项")

    def _remove_criterion_rows(self) -> None:
        rows = sorted(
            {index.row() for index in self.criteria_table.selectedIndexes()}, reverse=True
        )
        for row in rows:
            self.criteria_table.removeRow(row)
        self.criteria_count.setText(f"{self.criteria_table.rowCount()} 项")

    def _read_criteria(self) -> list[Criterion]:
        result = []
        for row in range(self.criteria_table.rowCount()):
            id_item = self.criteria_table.item(row, 0)
            name = self.criteria_table.item(row, 1).text().strip()
            definition = self.criteria_table.item(row, 2).text().strip()
            kind_widget = self.criteria_table.cellWidget(row, 3)
            weight_widget = self.criteria_table.cellWidget(row, 4)
            external_item = self.criteria_table.item(row, 5)
            raw_id = id_item.data(Qt.ItemDataRole.UserRole) or f"custom.{row + 1}"
            result.append(
                Criterion(
                    criterion_id=raw_id,
                    name=name,
                    definition=definition,
                    kind=kind_widget.currentData(),
                    weight=weight_widget.value(),
                    enabled=id_item.checkState() == Qt.CheckState.Checked,
                    requires_external_fact=external_item.checkState() == Qt.CheckState.Checked,
                )
            )
        return result

    def _start_screening(self) -> None:
        if not self.scan_result:
            QMessageBox.warning(self, "尚未扫描", "请返回任务配置页，先扫描简历根目录。")
            self.navigation.setCurrentRow(0)
            return
        output_text = self.output_root.text().strip()
        if not output_text:
            QMessageBox.warning(self, "缺少输出目录", "请选择输出目录。")
            return
        criteria = self._read_criteria()
        if not any(item.enabled for item in criteria):
            QMessageBox.warning(self, "没有启用条件", "请至少启用一个筛选条件。")
            return
        api_key = load_api_key()
        if not api_key:
            answer = QMessageBox.question(
                self,
                "未配置 API Key",
                "可以继续完成扫描、提取和 Excel，但所有语义判断都会标记为待复核。是否继续？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._open_settings()
                return
        else:
            answer = QMessageBox.question(
                self,
                "确认云端语义分析",
                "PDF/DOCX 原文件不会上传，但提取后的文本会在默认脱敏姓名、联系方式、地址"
                "和身份证号后发送至 DeepSeek API。自动脱敏可能遗漏信息，请确认你有权处理"
                "这些候选人材料并同意继续。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.criteria = criteria
        output = Path(output_text).expanduser().resolve()
        self.workspace = WorkspacePaths.create(output)
        self.database = Database(self.workspace.database)
        self.engine_thread = EngineThread(
            self.database,
            self.config,
            api_key,
            self.scan_result,
            criteria,
            self.jd.toPlainText(),
            self.requirements.toPlainText(),
            output,
        )
        self.engine_thread.progress_event.connect(self._on_progress)
        self.engine_thread.completed.connect(self._screening_completed)
        self.engine_thread.failed.connect(self._screening_failed)
        actual_workers = effective_worker_count(
            self.config.worker_count, len(self.scan_result.candidates)
        )
        self._reset_worker_labels(actual_workers)
        self.progress_bar.setRange(0, len(self.scan_result.candidates))
        self.progress_bar.setValue(0)
        self.event_log.clear()
        self.pause_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.start_button.setEnabled(False)
        self.navigation.setCurrentRow(2)
        self.engine_thread.start()

    def _on_progress(self, event: ProgressEvent) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        if event.message:
            self.event_log.appendPlainText(f"{timestamp}  {event.message}")
        self.progress_metric.setText(f"{event.completed} / {event.total}")
        self.progress_bar.setMaximum(max(1, event.total))
        self.progress_bar.setValue(event.completed)
        self.progress_state.setText(event.message)
        if event.worker and 1 <= event.worker <= len(self.worker_labels):
            self.worker_labels[event.worker - 1].setText(
                f"Worker {event.worker}  ·  {event.message}"
            )

    def _toggle_pause(self) -> None:
        if not self.engine_thread:
            return
        if self.pause_button.text() == "暂停":
            self.engine_thread.pause()
            self.pause_button.setText("继续")
            self.progress_state.setText("已暂停；正在执行的单个工具调用会安全结束")
        else:
            self.engine_thread.resume()
            self.pause_button.setText("暂停")
            self.progress_state.setText("继续处理中")

    def _cancel(self) -> None:
        if self.engine_thread:
            self.engine_thread.cancel()
            self.cancel_button.setEnabled(False)
            self.progress_state.setText("正在安全取消…")

    def _screening_completed(self, run_id: str, analyses: list[AnalysisResult]) -> None:
        self.run_id = run_id
        self.analyses = analyses
        self.pause_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.start_button.setEnabled(True)
        self._populate_results()
        self._export(silent=True)
        self.navigation.setCurrentRow(3)

    def _screening_failed(self, message: str) -> None:
        self.pause_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.start_button.setEnabled(True)
        QMessageBox.critical(self, "任务失败", message)

    def _populate_results(self) -> None:
        self.results_table.blockSignals(True)
        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(0)
        recommendation_labels = {
            "recommended": "推荐",
            "possible": "接近",
            "not_recommended": "不推荐",
            "review": "待复核",
        }
        sorted_results = sorted(self.analyses, key=lambda item: item.score, reverse=True)
        for rank, result in enumerate(sorted_results, 1):
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            check = QTableWidgetItem()
            check.setFlags(
                (check.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable
            )
            check.setCheckState(Qt.CheckState.Unchecked)
            self.results_table.setItem(row, 0, check)
            values = [
                rank,
                result.facts.name or self._candidate_name(result.candidate_id),
                result.score,
                recommendation_labels.get(result.recommendation, result.recommendation),
                result.facts.highest_degree or "",
                result.facts.current_or_last_company or "",
                sum(item.conclusion == Conclusion.UNCERTAIN for item in result.judgments),
                result.candidate_id,
            ]
            for col, value in enumerate(values, 1):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 3:
                    item.setData(Qt.ItemDataRole.EditRole, float(value))
                self.results_table.setItem(row, col, item)
            manual = (
                self.database.manual_fields_for(result.candidate_id)
                if self.database
                else {"hr_status": "", "owner": "", "note": ""}
            )
            for col, value in enumerate([manual["hr_status"], manual["owner"], manual["note"]], 9):
                self.results_table.setItem(row, col, QTableWidgetItem(value))
        self.results_table.setSortingEnabled(True)
        self.results_table.blockSignals(False)
        self.result_summary.setText(f"{len(self.analyses)} 名候选人 · 结果已按综合分排序")
        if self.results_table.rowCount():
            self.results_table.selectRow(0)

    def _manual_field_changed(self, item: QTableWidgetItem) -> None:
        if item.column() not in {9, 10, 11} or not self.database:
            return
        row = item.row()
        candidate = self.results_table.item(row, 8)
        if not candidate:
            return
        self.database.save_manual_fields(
            candidate.text(),
            self.results_table.item(row, 9).text(),
            self.results_table.item(row, 10).text(),
            self.results_table.item(row, 11).text(),
        )

    def _candidate_name(self, candidate_id: str) -> str:
        if self.scan_result:
            for package in self.scan_result.candidates:
                if package.candidate_id == candidate_id:
                    return package.display_name
        return candidate_id

    def _analysis_for_row(self, row: int) -> AnalysisResult | None:
        item = self.results_table.item(row, 8)
        if not item:
            return None
        return next((value for value in self.analyses if value.candidate_id == item.text()), None)

    def _show_evidence(self) -> None:
        rows = self.results_table.selectionModel().selectedRows()
        if not rows:
            return
        result = self._analysis_for_row(rows[0].row())
        if not result:
            return
        criteria = {item.criterion_id: item for item in self.criteria}
        recommendation_labels = {
            "recommended": "推荐",
            "possible": "接近",
            "not_recommended": "不推荐",
            "review": "待复核",
        }
        display_name = result.facts.name or self._candidate_name(result.candidate_id)
        recommendation = recommendation_labels.get(result.recommendation, result.recommendation)
        parts = [
            f"<h2>{escape_rich_text(display_name)}</h2>",
            f"<p><b>{result.score:.1f} 分 · "
            f"{escape_rich_text(recommendation)}</b></p>",
            f"<p>{escape_rich_text(result.overall_reason)}</p><hr>",
        ]
        labels = {"match": "符合", "no_match": "不符合", "uncertain": "不确定"}
        colors = {"match": "#0D7478", "no_match": "#A33C36", "uncertain": "#A36C17"}
        for judgment in result.judgments:
            criterion = criteria.get(judgment.criterion_id)
            title = criterion.name if criterion else judgment.criterion_id
            conclusion = str(judgment.conclusion)
            parts.append(
                f"<h3>{escape_rich_text(title)} "
                f"<span style='color:{colors.get(conclusion, '#555')};'>"
                f"{escape_rich_text(labels.get(conclusion, conclusion))}</span></h3>"
                f"<p>{escape_rich_text(judgment.reason)}</p>"
            )
            for evidence in judgment.evidence:
                parts.append(
                    f"<blockquote><b>{escape_rich_text(evidence.relative_path)}</b> · "
                    f"{escape_rich_text(evidence.locator_kind)} "
                    f"{escape_rich_text(evidence.locator_value)}<br>"
                    f"{escape_rich_text(evidence.quote)}</blockquote>"
                )
            if judgment.needs_external_fact:
                parts.append("<p style='color:#A36C17'>需要可信外部事实表核验</p>")
        self.evidence.setHtml("".join(parts))

    def _apply_result_filter(self) -> None:
        query = self.result_search.text().strip().lower()
        minimum = self.min_score.value()
        visible = 0
        for row in range(self.results_table.rowCount()):
            result = self._analysis_for_row(row)
            if not result:
                continue
            haystack = " ".join(
                [
                    result.facts.name or "",
                    result.facts.current_or_last_company or "",
                    " ".join(result.facts.skills),
                ]
            ).lower()
            show = result.score >= minimum and (not query or query in haystack)
            self.results_table.setRowHidden(row, not show)
            visible += int(show)
        self.result_summary.setText(f"当前显示 {visible} / {len(self.analyses)} 名候选人")

    def _export(self, silent: bool = False) -> None:
        if not self.scan_result or not self.analyses or not self.workspace or not self.run_id:
            if not silent:
                QMessageBox.information(self, "尚无结果", "请先完成一次筛选任务。")
            return
        audit = audit_run(self.scan_result, self.criteria, self.analyses, self.database)
        path = self.workspace.outputs / f"简历分析_{self.run_id}.xlsx"
        try:
            export_excel(
                path,
                self.run_id,
                self.scan_result,
                self.criteria,
                self.analyses,
                audit,
                self.database.all_manual_fields() if self.database else None,
            )
            if not silent:
                QMessageBox.information(self, "导出完成", f"Excel 已保存：\n{path}")
        except PermissionError:
            QMessageBox.critical(self, "文件被占用", "请关闭已打开的 Excel 文件后重试。")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _copy_selected(self) -> None:
        if not self.scan_result or not self.workspace or not self.run_id:
            QMessageBox.information(self, "尚无结果", "请先完成筛选。")
            return
        selected = set()
        for row in range(self.results_table.rowCount()):
            check = self.results_table.item(row, 0)
            candidate = self.results_table.item(row, 8)
            if check and check.checkState() == Qt.CheckState.Checked and candidate:
                selected.add(candidate.text())
        if not selected:
            QMessageBox.information(self, "没有勾选", "请在结果表第一列勾选需要整理材料的候选人。")
            return
        answer = QMessageBox.question(
            self,
            "确认复制材料",
            f"将复制 {len(selected)} 名候选人的完整原始子目录。原文件不会移动或删除。是否继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            manifest = copy_candidate_packages(
                self.scan_result.candidates,
                selected,
                self.workspace.outputs,
                self.run_id,
            )
            QMessageBox.information(self, "材料整理完成", f"复制校验通过，清单：\n{manifest}")
        except Exception as exc:
            QMessageBox.critical(self, "材料整理失败", str(exc))

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self, self.config)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.config = dialog.apply(self.config)
                self._save_runtime_settings()
                self._update_api_status()
            except Exception as exc:
                QMessageBox.critical(self, "设置保存失败", str(exc))

    def _update_api_status(self) -> None:
        self.api_status.setText("DeepSeek · 已配置" if load_api_key() else "DeepSeek · 未配置")

    def _restore_settings(self) -> None:
        self.resume_root.setText(self.settings.value("resume_root", ""))
        self.output_root.setText(self.settings.value("output_root", ""))
        try:
            count = max(
                1,
                min(16, int(self.settings.value("worker_count", self.config.worker_count))),
            )
        except (TypeError, ValueError):
            count = self.config.worker_count
        model = str(self.settings.value("model", self.config.model)).strip() or self.config.model
        redact = self.settings.value("redact_pii", self.config.redact_pii, type=bool)
        self.config = self.config.model_copy(
            update={
                "model": model,
                "worker_count": count,
                "extraction_concurrency": count,
                "analysis_concurrency": count,
                "redact_pii": redact,
            }
        )
        self._reset_worker_labels(count)

    def _save_runtime_settings(self) -> None:
        self.settings.setValue("worker_count", self.config.worker_count)
        self.settings.setValue("model", self.config.model)
        self.settings.setValue("redact_pii", self.config.redact_pii)

    def closeEvent(self, event) -> None:
        if self.engine_thread and self.engine_thread.isRunning():
            answer = QMessageBox.question(
                self,
                "任务仍在运行",
                "关闭后当前工具调用将中断；已落库结果仍会保留。确定关闭？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.engine_thread.cancel()
            self.engine_thread.wait(4000)
        self.settings.setValue("resume_root", self.resume_root.text())
        self.settings.setValue("output_root", self.output_root.text())
        self._save_runtime_settings()
        event.accept()
