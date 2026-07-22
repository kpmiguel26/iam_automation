from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Callable

from .startup import PreflightResult, StartupController, StartupState
from .webapp import launch_local_webapp_process

try:  # Optional until the desktop/web UI dependencies are installed.
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget
except ModuleNotFoundError:  # pragma: no cover - exercised when optional UI deps are absent
    QApplication = None  # type: ignore[assignment,misc]
    QFileDialog = None  # type: ignore[assignment,misc]
    Qt = QPixmap = None  # type: ignore[assignment,misc]
    QLabel = QLineEdit = QPlainTextEdit = QPushButton = QScrollArea = QVBoxLayout = QWidget = None  # type: ignore[assignment,misc]


class StartupWindow:
    """Qt view. It delegates all filesystem and identity decisions to the controller."""

    def __init__(self, controller: StartupController, *, on_ready: Callable[[PreflightResult], None] | None = None):
        if QWidget is None:
            raise RuntimeError("PySide6 is required to start the desktop preflight shell.")
        self.controller = controller
        self.on_ready = on_ready
        self.widget = QWidget()
        self.widget.setWindowTitle("IAM Automation - Environment Check")
        self.widget.setMinimumWidth(720)
        self.logo_label = QLabel()
        logo_path = Path(__file__).resolve().parent / "static" / "kaiser_permanente_logo.png"
        logo = QPixmap(str(logo_path))
        if not logo.isNull():
            self.logo_label.setPixmap(logo.scaledToHeight(58, Qt.TransformationMode.SmoothTransformation))
        self.status_label = QLabel()
        self.details_label = QLabel()
        self.details_label.setWordWrap(True)
        self.details_scroll = QScrollArea()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setWidget(self.details_label)
        self.details_scroll.setMinimumHeight(150)
        self.details_scroll.setMaximumHeight(260)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(150)
        self.path_input = QLineEdit()
        self.path_input.setReadOnly(True)
        self.browse_button = QPushButton("Browse")
        self.retry_button = QPushButton("Retry")
        self.start_button = QPushButton("Start Web App")
        self.open_button = QPushButton("Open App")
        self.open_button.setEnabled(False)
        self.webapp_url: str | None = None
        self.webapp_process = None
        layout = QVBoxLayout(self.widget)
        layout.addWidget(self.logo_label)
        layout.addWidget(QLabel("SharePoint / OneDrive synchronized folder"))
        layout.addWidget(self.path_input)
        layout.addWidget(self.status_label)
        layout.addWidget(self.details_scroll)
        layout.addWidget(QLabel("Startup log"))
        layout.addWidget(self.log_output)
        layout.addWidget(self.browse_button)
        layout.addWidget(self.retry_button)
        layout.addWidget(self.start_button)
        layout.addWidget(self.open_button)
        self.browse_button.clicked.connect(self.browse)
        self.retry_button.clicked.connect(self.retry)
        self.start_button.clicked.connect(self.continue_to_login)
        self.open_button.clicked.connect(self.open_app)

    def show(self) -> None:
        self.widget.show()

    def apply_result(self, result: PreflightResult) -> None:
        if result.settings:
            self.path_input.setText(str(result.settings.sharepoint_root_path))
        self.status_label.setText(f"{result.state.value}: {result.message}")
        details = [f"{item['label']}: {item['status']} - {item['message']}" for item in result.resources]
        self.details_label.setText("\n".join(details))
        self._log(f"[{result.state.value}] {result.message}")
        for item in result.resources:
            self._log(f"{item['label']}: {item['status']}")
        self.start_button.setEnabled(result.ok and self.webapp_url is None)
        self.open_button.setEnabled(self.webapp_url is not None)

    def _log(self, message: str) -> None:
        self.log_output.appendPlainText(message)

    def discover(self) -> PreflightResult:
        result = self.controller.discover_sharepoint()
        self.apply_result(result)
        return result

    def browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self.widget, "Select SharePoint synchronized folder")
        if selected:
            self.apply_result(self.controller.select_sharepoint_path(Path(selected)))

    def retry(self) -> None:
        self.apply_result(self.controller.retry())

    def mark_webapp_started(self, process, url: str) -> None:
        self.webapp_process = process
        self.webapp_url = url
        self.status_label.setText(f"READY: Local webapp is running at {url}")
        self._log(f"[WEBAPP] Flask/Waitress process started: {url}")
        self.details_label.setText(
            self.details_label.text()
            + f"\nWebapp process: running\nBrowser URL: {url}\nClick Open App when you are ready."
        )
        self.start_button.setEnabled(False)
        self.open_button.setEnabled(True)

    def open_app(self) -> None:
        if not self.webapp_url:
            return
        webbrowser.open(self.webapp_url)
        self._log(f"[BROWSER] Opened {self.webapp_url}")
        self.widget.close()
        application = QApplication.instance()
        if application is not None:
            application.quit()

    def continue_to_login(self) -> None:
        result = self.controller.validate_environment()
        self.apply_result(result)
        if not result.ok:
            return
        try:
            user = self.controller.continue_to_login()
            self._log(f"[IDENTITY] Approved user: {user.username} | roles: {', '.join(user.roles)}")
        except PermissionError as exc:
            self.status_label.setText(f"{StartupState.UNAUTHORIZED_USER.value}: {exc}")
            self.start_button.setEnabled(False)
            self.open_button.setEnabled(False)
            return
        if self.on_ready:
            self.on_ready(result)


def run_desktop_app(controller: StartupController | None = None) -> int:
    if QApplication is None:
        raise RuntimeError("PySide6 is required to run IAM Automation.")
    application = QApplication.instance() or QApplication([])
    startup_controller = controller or StartupController()
    server_holder = []

    def start_webapp(result: PreflightResult) -> None:
        try:
            process, url = launch_local_webapp_process(result, open_browser=False)
        except Exception as exc:
            window.status_label.setText(f"WEBAPP_ERROR: {exc}")
            window.details_label.setText(window.details_label.text() + f"\nWebapp startup failed: {exc}")
            window.start_button.setEnabled(True)
            window.open_button.setEnabled(False)
            return
        server_holder.append(process)
        window.mark_webapp_started(process, url)

    window = StartupWindow(startup_controller, on_ready=start_webapp)
    window.show()
    window.discover()
    return application.exec()
