import os
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QStackedWidget, QLineEdit,
                             QFrame, QGridLayout, QComboBox, QTextEdit,
                             QCheckBox, QFileDialog)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QIcon, QPixmap

from ui.styles import STYLESHEET
from ui.widgets import ActionButton
from core.config_manager import ConfigManager
from core.vm_manager import VMManager

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nekro-Agent 管理")
        self.resize(1050, 750)
        self.setStyleSheet(STYLESHEET)

        # 初始化后端
        self.config = ConfigManager()
        self.vm = VMManager()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- 1. 侧边栏 ---
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(15, 25, 15, 25)
        sidebar_layout.setSpacing(10)

        # Logo
        logo_layout = QHBoxLayout()
        logo_label = QLabel()
        logo_label.setFixedSize(36, 36)
        logo_label.setScaledContents(True)

        icon_path = os.path.join("assets", "NekroAgent.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            logo_label.setPixmap(QPixmap(icon_path))

        logo_text = QLabel("Nekro Agent")
        logo_text.setStyleSheet("font-size: 18px; font-weight: bold; color: #24292f; margin-left: 5px;")
        logo_layout.addWidget(logo_label); logo_layout.addWidget(logo_text); logo_layout.addStretch()
        sidebar_layout.addLayout(logo_layout)
        sidebar_layout.addSpacing(30)

        # 导航按钮
        self.btn_home = self.create_sidebar_btn("🏠", "项目概览", 0)
        self.btn_browser = self.create_sidebar_btn("🌐", "应用浏览器", 1)
        self.btn_logs = self.create_sidebar_btn("📝", "运行日志", 2)
        self.btn_files = self.create_sidebar_btn("📁", "文件管理", 3)
        sidebar_layout.addWidget(self.btn_home)
        sidebar_layout.addWidget(self.btn_browser)
        sidebar_layout.addWidget(self.btn_logs)
        sidebar_layout.addWidget(self.btn_files)
        sidebar_layout.addStretch()
        self.btn_settings = self.create_sidebar_btn("⚙️", "系统设置", 4)
        sidebar_layout.addWidget(self.btn_settings)

        main_layout.addWidget(self.sidebar)

        # --- 2. 右侧 Stack 布局 ---
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)

        self.init_home_page()
        self.init_browser_page()
        self.init_logs_page()
        self.init_empty_page("文件管理")
        self.init_settings_page()

        self.switch_tab(0)

        # 绑定后端信号
        self.vm.log_received.connect(self.append_log)
        self.vm.status_changed.connect(self.update_status_ui)
        self.setFocus()

        # 程序启动时自动启动虚拟机
        self.start_deploy()

    def create_sidebar_btn(self, icon, text, index):
        btn = QPushButton(f"  {icon}   {text}")
        btn.setObjectName("SidebarBtn")
        btn.setCheckable(True)
        btn.setFixedHeight(48)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda: self.switch_tab(index))
        return btn

    def switch_tab(self, index):
        self.stack.setCurrentIndex(index)
        btns = [self.btn_home, self.btn_browser, self.btn_logs, self.btn_files, self.btn_settings]
        for i, btn in enumerate(btns):
            btn.setChecked(i == index)

    def append_log(self, msg, level="info"):
        color = {"error": "#f85149", "warn": "#d29922", "vm": "#8b949e"}.get(level, "#7ee787")
        self.log_viewer.append(f"<span style='color:{color};'>[{level.upper()}]</span> {msg}")

    # --- 各页面具体实现 ---

    def init_home_page(self):
        page = QWidget(); layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40); layout.setSpacing(25)

        title_box = QVBoxLayout()
        lbl_title = QLabel("Nekro-Agent 环境管理")
        lbl_title.setStyleSheet("font-size: 26px; font-weight: bold;")
        self.lbl_status = QLabel("● 当前状态: 未就绪")
        self.lbl_status.setStyleSheet("font-size: 14px; color: #cf222e; margin-top: 5px;")
        title_box.addWidget(lbl_title); title_box.addWidget(self.lbl_status)
        layout.addLayout(title_box); layout.addSpacing(10)

        grid = QGridLayout(); grid.setSpacing(20)

        self.btn_download_vm = ActionButton("📥", "下载虚拟机镜像", "获取最新系统环境")
        self.btn_deploy_action = ActionButton("🚀", "一键部署项目", "自动配置 Docker 服务", "DeployBtn")
        self.btn_update_action = ActionButton("🔄", "检查环境更新", "更新镜像并重启")
        self.btn_uninstall_action = ActionButton("🗑️", "卸载清除环境", "删除所有容器和数据", "UninstallBtn")
        self.btn_web_home = ActionButton("🏠", "访问项目主页", "获取文档与支持")

        grid.addWidget(self.btn_download_vm, 0, 0)
        grid.addWidget(self.btn_deploy_action, 0, 1)
        grid.addWidget(self.btn_update_action, 1, 0)
        grid.addWidget(self.btn_uninstall_action, 1, 1)
        grid.addWidget(self.btn_web_home, 2, 0, 1, 2)

        # 绑定按钮事件
        self.btn_deploy_action.clicked.connect(self.start_deploy)

        layout.addLayout(grid); layout.addStretch()
        self.stack.addWidget(page)

    def start_deploy(self):
        # 扫描 ISO 镜像
        iso_dir = os.path.join(self.vm.base_path, "v-core")
        if not os.path.exists(iso_dir):
            os.makedirs(iso_dir)

        isos = [f for f in os.listdir(iso_dir) if f.endswith(".iso")]

        if not isos:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "错误", "未在 v-core 目录发现任何 ISO 镜像文件")
            return

        selected_iso = None
        if len(isos) == 1:
            selected_iso = isos[0]
        else:
            # 存在多个 ISO，尝试从配置读取上次的选择，或者弹出选择框
            last_iso = self.config.get("last_iso")
            if last_iso in isos:
                selected_iso = last_iso
            else:
                from PyQt6.QtWidgets import QInputDialog
                item, ok = QInputDialog.getItem(self, "选择环境版本",
                                                "检测到多个系统镜像，请选择一个启动:",
                                                isos, 0, False)
                if ok and item:
                    selected_iso = item
                else:
                    return

        # 记录最后一次的选择并更新 UI
        self.config.set("last_iso", selected_iso)
        if hasattr(self, 'iso_edit'):
            self.iso_edit.setText(selected_iso)

        full_iso_path = os.path.join(iso_dir, selected_iso)

        # 切换到日志页查看进度
        self.switch_tab(2)
        # 启动虚拟机 (正确传递参数)
        self.vm.start_vm(iso_path=full_iso_path, custom_shared_dir=self.config.get("shared_dir"))

    def update_status_ui(self, status):
        self.lbl_status.setText(f"● 当前状态: {status}")
        if status == "运行中":
            self.lbl_status.setStyleSheet("font-size: 14px; color: #2da44e; margin-top: 5px;")
            # 自动跳转浏览器
            self.webview.setUrl(QUrl("http://localhost:8021"))
        else:
            self.lbl_status.setStyleSheet("font-size: 14px; color: #cf222e; margin-top: 5px;")

    def init_browser_page(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        toolbar = QFrame(); toolbar.setObjectName("TopBar"); toolbar.setFixedHeight(55)
        tb_layout = QHBoxLayout(toolbar); tb_layout.setContentsMargins(15, 0, 15, 0)

        self.url_bar = QLineEdit(); self.url_bar.setObjectName("UrlBar")
        self.url_bar.setText("http://localhost:8021"); self.url_bar.setReadOnly(True)

        btn_back = QPushButton("◀")
        btn_back.setFixedSize(32, 32)
        btn_back.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        tb_layout.addWidget(btn_back)
        tb_layout.addWidget(self.url_bar)
        layout.addWidget(toolbar)

        self.webview = QWebEngineView()
        self.webview.setHtml("<html><body style='background-color:#f6f8fa; display:flex; justify-content:center; align-items:center; height:100vh; font-family:sans-serif; color:#8b949e;'><h2>启动后将自动连接服务界面</h2></body></html>")
        layout.addWidget(self.webview); self.stack.addWidget(page)

    def init_logs_page(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(25, 25, 25, 25); layout.setSpacing(15)
        top = QHBoxLayout()
        self.log_source = QComboBox()
        self.log_source.addItems(["虚拟机日志", "Docker日志", "Agent容器日志"])
        top.addWidget(QLabel("选择日志源:")); top.addWidget(self.log_source); top.addStretch()
        layout.addLayout(top)
        self.log_viewer = QTextEdit(); self.log_viewer.setObjectName("LogViewer"); self.log_viewer.setReadOnly(True)
        layout.addWidget(self.log_viewer); self.stack.addWidget(page)

    def init_settings_page(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(40, 40, 40, 40); layout.setSpacing(30)
        lbl_title = QLabel("系统设置"); lbl_title.setStyleSheet("font-size: 24px; font-weight: bold; color: #24292f;")
        layout.addWidget(lbl_title)

        self.check_auto = QCheckBox("开机自动启动 Nekro-Agent 管理系统")
        self.check_auto.setChecked(self.config.get("autostart"))
        self.check_auto.stateChanged.connect(lambda s: self.config.set("autostart", s == 2))
        layout.addWidget(self.check_auto)

        lbl_dir = QLabel("共享目录:"); layout.addWidget(lbl_dir)
        path_box = QHBoxLayout()
        self.path_edit = QLineEdit(self.config.get("shared_dir"))
        self.path_edit.setReadOnly(True)
        btn_sel = QPushButton("选择目录")
        btn_sel.setFixedHeight(35)
        btn_sel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_sel.clicked.connect(self.select_dir)
        path_box.addWidget(self.path_edit); path_box.addWidget(btn_sel)
        layout.addLayout(path_box)

        lbl_iso = QLabel("当前环境镜像:"); layout.addWidget(lbl_iso)
        self.iso_edit = QLineEdit(self.config.get("last_iso") or "启动时自动检测")
        self.iso_edit.setReadOnly(True)
        layout.addWidget(self.iso_edit)

        layout.addStretch(); self.stack.addWidget(page)

    def select_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择共享目录", os.getcwd())
        if d:
            self.path_edit.setText(d)
            self.config.set("shared_dir", d)

    def init_empty_page(self, title):
        page = QWidget(); layout = QVBoxLayout(page); layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(QLabel(f"<h3>{title}</h3> 模块开发中..."))
        self.stack.addWidget(page)
