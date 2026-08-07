from __future__ import annotations

import ctypes
import sys
import webbrowser
from pathlib import Path
from typing import Callable

from .startup import PreflightResult, StartupController, StartupState
from .webapp import launch_local_webapp_process, stop_local_webapp, webapp_pid_path

try:  # Optional until the desktop/web UI dependencies are installed.
    from PySide6.QtCore import Qt, QThread, Signal
    from PySide6.QtGui import QIcon, QPixmap
    from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QProgressBar, QScrollArea, QVBoxLayout, QWidget
except ModuleNotFoundError:  # pragma: no cover - exercised when optional UI deps are absent
    QApplication = None  # type: ignore[assignment,misc]
    QFileDialog = None  # type: ignore[assignment,misc]
    Qt = QIcon = QPixmap = QThread = Signal = None  # type: ignore[assignment,misc]
    QApplication = QFileDialog = QFrame = QHBoxLayout = QLabel = QLineEdit = QPlainTextEdit = QPushButton = QProgressBar = QScrollArea = QVBoxLayout = QWidget = None  # type: ignore[assignment,misc]


if QThread is not None:
    class PreflightWorker(QThread):
        completed = Signal(object)
        failed = Signal(str)

        def __init__(self, controller: StartupController, operation: str, path: Path | None = None):
            super().__init__()
            self.controller = controller
            self.operation = operation
            self.path = path

        def run(self) -> None:
            try:
                if self.operation == "discover":
                    result = self.controller.discover_sharepoint()
                elif self.operation == "select" and self.path is not None:
                    result = self.controller.select_sharepoint_path(self.path)
                elif self.operation == "retry":
                    result = self.controller.retry()
                elif self.operation == "validate":
                    result = self.controller.validate_environment()
                else:
                    raise RuntimeError("Unknown preflight operation.")
                self.completed.emit(result)
            except Exception as exc:  # pragma: no cover - depends on local SharePoint/OneDrive state
                self.failed.emit(f"{type(exc).__name__}: {exc}")


class StartupWindow:
    """Qt view. It delegates all filesystem and identity decisions to the controller."""

    def __init__(self, controller: StartupController, *, on_ready: Callable[[PreflightResult], None] | None = None):
        if QWidget is None:
            raise RuntimeError("PySide6 is required to start the desktop preflight shell.")
        self.controller = controller
        self.on_ready = on_ready
        self.widget = QWidget()
        self.widget.setWindowTitle("IAM Automation - Environment Check")
        icon_path = Path(__file__).resolve().parent / "static" / "preflight_icon.svg"
        if icon_path.is_file():
            self.widget.setWindowIcon(QIcon(str(icon_path)))
        self.widget.resize(940, 720)
        self.widget.setMinimumSize(760, 560)
        self.widget.setStyleSheet(
            """
            QWidget { background: #f4f7fb; color: #17233f; font-family: "Helvetica Neue", Arial, sans-serif; font-size: 13px; }
            QLabel { background: transparent; }
            QFrame#header { background: #10254d; border-radius: 10px; }
            QLabel#logo { background: transparent; }
            QLabel#productName { background: transparent; color: #ffffff; font-size: 20px; font-weight: 700; }
            QLabel#productSubtitle { background: transparent; color: #b8c7e2; font-size: 12px; }
            QLabel#headerTag { background: transparent; color: #7ce1d4; font-size: 11px; font-weight: 700; }
            QLabel#sectionLabel { color: #087f83; font-size: 11px; font-weight: 700; padding-top: 8px; }
            QLabel#statusLabel { background: #fff4d6; border: 1px solid #f0d58c; border-radius: 8px; color: #75540b; font-size: 14px; font-weight: 600; padding: 11px 14px; }
            QLabel#statusLabel[ready="true"] { background: #e5f6ed; border-color: #a8dfc0; color: #17653c; }
            QLabel#statusLabel[error="true"] { background: #fde9e7; border-color: #efb1ab; color: #9d2f2a; }
            QProgressBar#preflightProgress { background: #e9eef5; border: 0; border-radius: 3px; height: 6px; }
            QProgressBar#preflightProgress::chunk { background: #087f83; border-radius: 3px; }
            QLineEdit, QPlainTextEdit { background: white; border: 1px solid #d7dfec; border-radius: 7px; padding: 8px; }
            QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #2e74c9; }
            QScrollArea { background: white; border: 1px solid #d7dfec; border-radius: 7px; }
            QPushButton { background: #edf2f8; border: 1px solid #cbd6e5; border-radius: 6px; color: #1b3157; font-weight: 600; padding: 8px 14px; min-height: 18px; }
            QPushButton:hover { background: #e1eaf5; border-color: #8ca8ca; }
            QPushButton:disabled { color: #9aa6b8; background: #eef1f5; border-color: #dfe4eb; }
            QPushButton#primaryButton { background: #1266d6; border-color: #1266d6; color: white; }
            QPushButton#primaryButton:hover { background: #0c55b6; }
            QPushButton#successButton { background: #16834b; border-color: #16834b; color: white; }
            QPushButton#dangerButton { color: #9d2f2a; border-color: #e2aaa6; }
            """
        )
        self.logo_label = QLabel()
        self.logo_label.setObjectName("logo")
        logo_path = Path(__file__).resolve().parent / "static" / "kaiser_permanente_logo.png"
        logo = QPixmap(str(logo_path))
        if not logo.isNull():
            self.logo_label.setPixmap(logo.scaledToHeight(58, Qt.TransformationMode.SmoothTransformation))
        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        self.preflight_progress = QProgressBar()
        self.preflight_progress.setObjectName("preflightProgress")
        self.preflight_progress.setRange(0, 0)
        self.preflight_progress.setTextVisible(False)
        self.preflight_progress.setVisible(False)
        self.details_label = QLabel()
        self.details_label.setWordWrap(True)
        self.details_scroll = QScrollArea()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setWidget(self.details_label)
        self.details_scroll.setMinimumHeight(150)
        self.details_scroll.setMaximumHeight(230)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(100)
        self.log_output.setMaximumHeight(170)
        self.path_input = QLineEdit()
        self.path_input.setReadOnly(True)
        self.browse_button = QPushButton("Browse")
        self.retry_button = QPushButton("Retry")
        self.start_button = QPushButton("Start Web App")
        self.open_button = QPushButton("Open App")
        self.stop_button = QPushButton("Stop Web App")
        self.browse_button.setObjectName("secondaryButton")
        self.retry_button.setObjectName("secondaryButton")
        self.start_button.setObjectName("primaryButton")
        self.open_button.setObjectName("successButton")
        self.stop_button.setObjectName("dangerButton")
        self.open_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.webapp_url: str | None = None
        self.webapp_process = None
        self.preflight_worker = None
        self.preflight_callback = None
        self.closing = False
        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)
        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 18, 12)
        header_layout.addWidget(self.logo_label)
        header_layout.addSpacing(14)
        brand = QVBoxLayout()
        product = QLabel("IAM Automation")
        product.setObjectName("productName")
        subtitle = QLabel("Local workspace control panel")
        subtitle.setObjectName("productSubtitle")
        brand.addWidget(product)
        brand.addWidget(subtitle)
        header_layout.addLayout(brand)
        header_layout.addStretch()
        self.preflight_icon = QLabel()
        self.preflight_icon.setObjectName("preflightIcon")
        self.preflight_icon.setToolTip("Environment preflight gate")
        icon = QIcon(str(icon_path))
        if not icon.isNull():
            self.preflight_icon.setPixmap(icon.pixmap(30, 30))
        header_layout.addWidget(self.preflight_icon)
        header_tag = QLabel("PREFLIGHT")
        header_tag.setObjectName("headerTag")
        header_layout.addWidget(header_tag)
        layout.addWidget(header)

        path_label = QLabel("SHAREPOINT / ONEDRIVE SYNCHRONIZED FOLDER")
        path_label.setObjectName("sectionLabel")
        layout.addWidget(path_label)
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        path_row.addWidget(self.path_input, 1)
        path_row.addWidget(self.browse_button)
        layout.addLayout(path_row)
        layout.addWidget(self.status_label)
        layout.addWidget(self.preflight_progress)

        details_label = QLabel("VALIDATION DETAILS")
        details_label.setObjectName("sectionLabel")
        layout.addWidget(details_label)
        layout.addWidget(self.details_scroll)
        log_label = QLabel("STARTUP LOG")
        log_label.setObjectName("sectionLabel")
        layout.addWidget(log_label)
        layout.addWidget(self.log_output)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch()
        actions.addWidget(self.retry_button)
        actions.addWidget(self.start_button)
        actions.addWidget(self.open_button)
        actions.addWidget(self.stop_button)
        layout.addLayout(actions)
        self.browse_button.clicked.connect(self.browse)
        self.retry_button.clicked.connect(self.retry)
        self.start_button.clicked.connect(self.continue_to_login)
        self.open_button.clicked.connect(self.open_app)
        self.stop_button.clicked.connect(self.stop_webapp)

    def show(self) -> None:
        self.widget.show()

    def apply_result(self, result: PreflightResult) -> None:
        if result.settings:
            self.path_input.setText(str(result.settings.sharepoint_root_path))
        self._set_status(f"{result.state.value}: {result.message}", ready=result.ok, error=not result.ok)
        details = [f"{item['label']}: {item['status']} - {item['message']}" for item in result.resources]
        self.details_label.setText("\n".join(details))
        self._log(f"[{result.state.value}] {result.message}")
        for item in result.resources:
            self._log(f"{item['label']}: {item['status']}")
        self.start_button.setEnabled(result.ok and self.webapp_url is None)
        self.open_button.setEnabled(self.webapp_url is not None)

    def _log(self, message: str) -> None:
        self.log_output.appendPlainText(message)

    def _set_status(self, message: str, *, ready: bool = False, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.setProperty("ready", ready)
        self.status_label.setProperty("error", error)
        style = self.status_label.style()
        style.unpolish(self.status_label)
        style.polish(self.status_label)

    def _set_preflight_busy(self, busy: bool, message: str = "") -> None:
        self.preflight_progress.setVisible(busy)
        self.browse_button.setEnabled(not busy)
        self.retry_button.setEnabled(not busy)
        self.start_button.setEnabled(not busy and bool(self.controller.result and self.controller.result.ok) and self.webapp_url is None)
        if busy and message:
            self._set_status(message)

    def _run_preflight(self, operation: str, *, path: Path | None = None, callback: Callable[[PreflightResult], None] | None = None) -> None:
        if self.preflight_worker is not None or PreflightWorker is None:
            return
        self.preflight_callback = callback
        labels = {"discover": "CHECKING: Discovering the synchronized workspace...", "select": "CHECKING: Validating the selected workspace...", "retry": "CHECKING: Retrying environment validation...", "validate": "CHECKING: Validating SharePoint, databases and local folders..."}
        self._set_preflight_busy(True, labels.get(operation, "CHECKING: Validating environment..."))
        worker = PreflightWorker(self.controller, operation, path)
        self.preflight_worker = worker
        worker.completed.connect(self._preflight_completed)
        worker.failed.connect(self._preflight_failed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _preflight_completed(self, result: PreflightResult) -> None:
        callback = self.preflight_callback
        self.preflight_callback = None
        self.preflight_worker = None
        self._set_preflight_busy(False)
        self.apply_result(result)
        if callback:
            callback(result)

    def _preflight_failed(self, message: str) -> None:
        self.preflight_callback = None
        self.preflight_worker = None
        self._set_preflight_busy(False)
        self._set_status(f"PREFLIGHT_ERROR: {message}", error=True)
        self._log(f"[PREFLIGHT] {message}")

    def discover(self) -> None:
        self._run_preflight("discover")

    def browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self.widget, "Select SharePoint synchronized folder")
        if selected:
            self._run_preflight("select", path=Path(selected))

    def retry(self) -> None:
        self._run_preflight("retry")

    def mark_webapp_started(self, process, url: str) -> None:
        self.webapp_process = process
        self.webapp_url = url
        self._set_status(f"READY: Local webapp is running at {url}", ready=True)
        self._log(f"[WEBAPP] Flask/Waitress process started: {url}")
        self.details_label.setText(
            self.details_label.text()
            + f"\nWebapp process: running\nBrowser URL: {url}\nClick Open App when you are ready."
        )
        self.start_button.setEnabled(False)
        self.open_button.setEnabled(True)
        self.stop_button.setEnabled(True)

    def stop_webapp(self) -> None:
        if not self.webapp_url:
            return
        self.stop_button.setEnabled(False)
        self._set_status("STOPPING: Requesting a clean webapp shutdown...")
        self.stop_worker = WebAppStopWorker()
        self.stop_worker.stopped.connect(self._webapp_stopped)
        self.stop_worker.failed.connect(self._webapp_stop_failed)
        self.stop_worker.finished.connect(self.stop_worker.deleteLater)
        self.stop_worker.start()

    def _webapp_stopped(self) -> None:
        self._log("[WEBAPP] Stop request sent successfully.")
        self.webapp_url = None
        self.webapp_process = None
        self.start_button.setEnabled(True)
        self.open_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self._set_status("READY: Webapp stopped. The control panel remains available.", ready=True)
        if self.closing:
            self._finish_exit()

    def _webapp_stop_failed(self, message: str) -> None:
        self._log(f"[WEBAPP] Stop request failed: {message}")
        if not webapp_pid_path().exists():
            self._webapp_stopped()
            self._set_status("READY: Stale webapp session cleared. Start the webapp again.", ready=True)
            return
        self.stop_button.setEnabled(True)
        self._set_status(f"STOP_ERROR: {message}", error=True)

    def exit_app(self) -> None:
        if self.webapp_url:
            self.closing = True
            self.stop_webapp()
            return
        self._finish_exit()

    def _finish_exit(self) -> None:
        application = QApplication.instance()
        if application is not None:
            application.quit()

    def mark_webapp_starting(self) -> None:
        self._set_status("STARTING: Local Flask/Waitress webapp...")
        self._log("[WEBAPP] Starting Flask/Waitress process...")
        self.start_button.setEnabled(False)
        self.open_button.setEnabled(False)

    def open_app(self) -> None:
        if not self.webapp_url:
            return
        if not webapp_pid_path().exists():
            self._log("[WEBAPP] Stale webapp session detected; resetting control panel.")
            self._webapp_stopped()
            self._set_status("READY: Webapp session expired. Start the webapp again.", ready=True)
            return
        webbrowser.open(self.webapp_url)
        self._log(f"[BROWSER] Opened {self.webapp_url}")

    def continue_to_login(self) -> None:
        self._run_preflight("validate", callback=self._continue_after_validation)

    def _continue_after_validation(self, result: PreflightResult) -> None:
        if not result.ok:
            return
        try:
            user = self.controller.continue_to_login()
            self._log(f"[IDENTITY] Windows identity recorded: {user.username} on {user.computer} | application login required")
        except PermissionError as exc:
            self._set_status(f"{StartupState.UNAUTHORIZED_USER.value}: {exc}", error=True)
            self.start_button.setEnabled(False)
            self.open_button.setEnabled(False)
            return
        if self.on_ready:
            self.on_ready(result)


if QThread is not None:
    class WebAppStartupWorker(QThread):
        ready = Signal(object, str)
        failed = Signal(str)

        def __init__(self, result: PreflightResult):
            super().__init__()
            self.result = result

        def run(self) -> None:
            try:
                process, url = launch_local_webapp_process(self.result, open_browser=False)
            except Exception as exc:  # pragma: no cover - depends on local process startup
                self.failed.emit(str(exc))
                return
            self.ready.emit(process, url)

    class WebAppStopWorker(QThread):
        stopped = Signal()
        failed = Signal(str)

        def run(self) -> None:
            try:
                stop_local_webapp()
            except Exception as exc:  # pragma: no cover - depends on local process state
                self.failed.emit(str(exc))
                return
            self.stopped.emit()
else:  # pragma: no cover - only used when the optional UI dependency is absent
    WebAppStartupWorker = None  # type: ignore[assignment,misc]
    WebAppStopWorker = None  # type: ignore[assignment,misc]


def run_desktop_app(controller: StartupController | None = None) -> int:
    if QApplication is None:
        raise RuntimeError("PySide6 is required to run IAM Automation.")
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("KaiserPermanente.IAMAutomation")
        except (AttributeError, OSError):
            pass
    application = QApplication.instance() or QApplication([])
    application.setApplicationName("IAM Automation")
    application.setApplicationDisplayName("IAM Automation")
    application_icon = Path(__file__).resolve().parent / "static" / "preflight_icon.svg"
    if application_icon.is_file():
        application.setWindowIcon(QIcon(str(application_icon)))
    startup_controller = controller or StartupController()
    server_holder = []
    startup_workers = []

    def start_webapp(result: PreflightResult) -> None:
        if WebAppStartupWorker is None:
            window.status_label.setText("WEBAPP_ERROR: PySide6 worker support is unavailable.")
            return
        window.mark_webapp_starting()
        worker = WebAppStartupWorker(result)
        startup_workers.append(worker)
        worker.ready.connect(lambda process, url: (server_holder.append(process), window.mark_webapp_started(process, url)))
        worker.failed.connect(lambda message: (
            window.status_label.setText(f"WEBAPP_ERROR: {message}"),
            window.details_label.setText(window.details_label.text() + f"\nWebapp startup failed: {message}"),
            window.start_button.setEnabled(True),
            window.open_button.setEnabled(False),
        ))
        worker.finished.connect(lambda: startup_workers.remove(worker) if worker in startup_workers else None)
        worker.start()

    window = StartupWindow(startup_controller, on_ready=start_webapp)
    window.show()
    window.discover()
    return application.exec()
