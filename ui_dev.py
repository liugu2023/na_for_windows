import sys
import os
import requests
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QStackedWidget,
                             QLineEdit, QFrame, QSizePolicy, QProgressBar)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl, Qt, QSize, qInstallMessageHandler, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QFont, QAction, QPixmap

# --- 屏蔽 Qt 繁琐日志 ---
def qt_message_handler(mode, context, message):
    if "libpng warning" in message or "Accessibility" in message:
        return
    # print(f"[Qt] {message}")

qInstallMessageHandler(qt_message_handler)

# --- 样式表 (CSS) ---
STYLESHEET = """
QMainWindow {
    background-color: #f6f8fa;
}

/* 侧边栏 */
QFrame#Sidebar {
    background-color: #ffffff;
    border-right: 1px solid #d0d7de;
}

QPushButton.SidebarBtn {
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 0 15px;
    text-align: left;
    color: #57606a;
    font-size: 14px;
    font-weight: 600;
}
QPushButton.SidebarBtn:hover {
    background-color: #f3f4f6;
    color: #24292f;
}
QPushButton.SidebarBtn:checked {
    background-color: #ddf4ff;
    color: #0969da;
}

/* 顶部工具栏 */
QFrame#TopBar {
    background-color: #ffffff;
    border-bottom: 1px solid #d0d7de;
}

QLineEdit#UrlBar {
    background-color: #f6f8fa;
    border: 1px solid #d0d7de;
    border-radius: 6px;
    padding: 4px 10px;
    color: #57606a;
    font-size: 13px;
}

/* 卡片按钮 */
QPushButton#ActionBtn {
    background-color: #ffffff;
    border: 1px solid #d0d7de;
    border-radius: 8px;
    text-align: left;
    padding: 15px;
}
QPushButton#ActionBtn:hover {
    border-color: #0969da;
    background-color: #f6f8fa;
}
QPushButton#ActionBtn:pressed {
    background-color: #f3f4f6;
}

QLabel#ActionTitle {
    font-size: 16px;
    font-weight: bold;
    color: #24292f;
}
QLabel#ActionDesc {
    font-size: 12px;
    color: #57606a;
    margin-top: 4px;
}

/* 占位页 */
QLabel#EmptyTitle {
    color: #24292f;
    font-size: 18px;
    font-weight: bold;
}
QLabel#EmptyDesc {
    color: #8b949e;
    font-size: 14px;
}
"""

# --- 自定义组件 ---

class ActionButton(QPushButton):
    def __init__(self, icon, title, desc, parent=None):
        super().__init__(parent)
        self.setObjectName("ActionBtn")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(100)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(15)

        # 图标
        lbl_icon = QLabel(icon)
        lbl_icon.setStyleSheet("font-size: 32px; border: none; background: transparent;")
        layout.addWidget(lbl_icon)

        # 文本区域
        text_container = QWidget()
        text_container.setStyleSheet("background: transparent; border: none;")
        v_layout = QVBoxLayout(text_container)
        v_layout.setContentsMargins(0, 5, 0, 5)
        v_layout.setSpacing(2)

        lbl_title = QLabel(title)
        lbl_title.setObjectName("ActionTitle")
        lbl_desc = QLabel(desc)
        lbl_desc.setObjectName("ActionDesc")

        v_layout.addWidget(lbl_title)
        v_layout.addWidget(lbl_desc)
        v_layout.addStretch()

        layout.addWidget(text_container)
        layout.addStretch()

# --- 主窗口 ---

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nekro-Agent 管理")
        self.resize(1000, 700)
        self.setStyleSheet(STYLESHEET)

        # 主布局容器
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- 1. 左侧侧边栏 ---
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 20, 10, 20)
        sidebar_layout.setSpacing(10)

        # Logo
        logo_layout = QHBoxLayout()
        logo_label = QLabel()
        logo_label.setFixedSize(32, 32)
        logo_label.setScaledContents(True)

        logo_text = QLabel("Nekro Agent")
        logo_text.setStyleSheet("font-size: 16px; font-weight: bold; color: #24292f; margin-left: 8px;")

        # 加载图标 (优先加载 png，其次 webp)
        icon_path_png = "NekroAgent.png"
        icon_path_webp = "NekroAgent.webp"

        final_icon_path = None
        if os.path.exists(icon_path_png):
            final_icon_path = icon_path_png
        elif os.path.exists(icon_path_webp):
            final_icon_path = icon_path_webp

        if final_icon_path:
            self.setWindowIcon(QIcon(final_icon_path)) # 设置窗口图标
            pixmap = QPixmap(final_icon_path)
            if not pixmap.isNull():
                logo_label.setPixmap(pixmap)
                logo_label.setStyleSheet("background: transparent;")
            else:
                self._set_fallback_logo(logo_label)
        else:
            self._set_fallback_logo(logo_label)

        logo_layout.addWidget(logo_label)
        logo_layout.addWidget(logo_text)
        logo_layout.addStretch()

        sidebar_layout.addLayout(logo_layout)

        sidebar_layout.addSpacing(20)

        # 侧边栏按钮组
        self.btn_home = self.create_sidebar_btn("🏠", "项目概览")
        self.btn_browser = self.create_sidebar_btn("🌐", "应用浏览器")
        self.btn_logs = self.create_sidebar_btn("📝", "运行日志")
        self.btn_files = self.create_sidebar_btn("📁", "文件管理")

        sidebar_layout.addWidget(self.btn_home)
        sidebar_layout.addWidget(self.btn_browser)
        sidebar_layout.addWidget(self.btn_logs)
        sidebar_layout.addWidget(self.btn_files)

        sidebar_layout.addStretch() # 弹簧占位

        self.btn_settings = self.create_sidebar_btn("⚙️", "系统设置")
        sidebar_layout.addWidget(self.btn_settings)

        main_layout.addWidget(self.sidebar)

        # --- 2. 右侧主区域 ---
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)

        # 初始化各个页面
        self.init_home_page()
        self.init_browser_page()
        self.init_empty_page("运行日志")
        self.init_empty_page("文件管理")
        self.init_empty_page("系统设置")

        # 默认显示主页
        self.switch_tab(0)

    def _set_fallback_logo(self, label):
        label.setText("N")
        label.setStyleSheet("background-color: #24292f; color: white; border-radius: 8px; font-weight: bold; font-size: 20px;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def create_sidebar_btn(self, icon_text, text):
        # 按钮文字包含图标和描述
        btn = QPushButton(f"  {icon_text}   {text}")
        btn.setObjectName("SidebarBtn")
        # 此时 text 即为 tooltip/ID
        btn.setCheckable(True)
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        # 绑定点击事件
        index_map = {
            "项目概览": 0, "应用浏览器": 1, "运行日志": 2,
            "文件管理": 3, "系统设置": 4
        }
        if text in index_map:
            btn.clicked.connect(lambda: self.switch_tab(index_map[text]))

        return btn

    def switch_tab(self, index):
        self.stack.setCurrentIndex(index)

        # 更新按钮选中状态
        btns = [self.btn_home, self.btn_browser, self.btn_logs, self.btn_files, self.btn_settings]
        for i, btn in enumerate(btns):
            btn.setChecked(i == index)

    # --- 页面初始化 ---

    def init_home_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        # 1. 顶部状态区
        header_layout = QHBoxLayout()

        # 标题
        title_box = QVBoxLayout()
        lbl_title = QLabel("Nekro-Agent 环境管理")
        lbl_title.setStyleSheet("font-size: 24px; font-weight: bold; color: #24292f;")
        lbl_status = QLabel("● 当前状态: 未启动")
        lbl_status.setStyleSheet("font-size: 14px; color: #cf222e; margin-top: 5px;") # 默认红色
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_status)

        header_layout.addLayout(title_box)
        header_layout.addStretch()

        layout.addLayout(header_layout)
        layout.addSpacing(20)

        # 2. 功能按钮区 (Grid Layout)
        from PyQt6.QtWidgets import QGridLayout
        grid = QGridLayout()
        grid.setSpacing(20)

        # 按钮 0: 下载系统镜像
        btn_download = ActionButton("📥", "下载系统镜像", "从云端获取最新虚拟机镜像")
        grid.addWidget(btn_download, 0, 0)

        # 按钮 1: 一键部署
        btn_deploy = ActionButton("🚀", "一键部署", "启动虚拟机并运行 Docker 服务")
        btn_deploy.setStyleSheet("""
            QPushButton#ActionBtn { border: 1px solid #2da44e; background-color: #f6fff8; }
            QPushButton#ActionBtn:hover { background-color: #e6ffec; }
        """)
        grid.addWidget(btn_deploy, 0, 1)

        # 按钮 2: 检查更新
        btn_update = ActionButton("🔄", "检查更新", "拉取最新镜像并重启服务")
        grid.addWidget(btn_update, 1, 0)

        # 按钮 3: 卸载清除
        btn_uninstall = ActionButton("🗑️", "卸载清除", "删除容器、镜像及数据")
        btn_uninstall.setStyleSheet("""
            QPushButton#ActionBtn:hover { border-color: #cf222e; background-color: #fff8f8; }
        """)
        grid.addWidget(btn_uninstall, 1, 1)

        # 按钮 4: 项目主页 (跨两列)
        btn_web = ActionButton("🏠", "项目主页", "访问官方文档与社区")
        grid.addWidget(btn_web, 2, 0, 1, 2)

        layout.addLayout(grid)
        layout.addStretch() # 底部留白

        self.stack.addWidget(page)

    def init_browser_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 浏览器工具栏
        toolbar = QFrame()
        toolbar.setObjectName("TopBar")
        toolbar.setFixedHeight(50)
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(10, 0, 10, 0)

        # 导航按钮
        btn_back = QPushButton("◀")
        btn_back.setFixedSize(30, 30)
        btn_forward = QPushButton("▶")
        btn_forward.setFixedSize(30, 30)
        btn_reload = QPushButton("🔄")
        btn_reload.setFixedSize(30, 30)

        # 地址栏
        self.url_bar = QLineEdit()
        self.url_bar.setObjectName("UrlBar")
        self.url_bar.setText("http://localhost:8080")
        self.url_bar.setReadOnly(True) # 暂时只读

        # 外部浏览器按钮
        btn_open = QPushButton("外部打开")

        tb_layout.addWidget(btn_back)
        tb_layout.addWidget(btn_forward)
        tb_layout.addWidget(btn_reload)
        tb_layout.addWidget(self.url_bar)
        tb_layout.addWidget(btn_open)

        layout.addWidget(toolbar)

        # WebEngineView
        self.webview = QWebEngineView()
        # 默认不加载 URL (留白)
        self.webview.setHtml("""
            <html><body style='background-color:#f6f8fa; display:flex; justify-content:center; align-items:center; height:100vh; font-family:sans-serif; color:#8b949e;'>
            <h2>请先启动服务</h2>
            </body></html>
        """)
        layout.addWidget(self.webview)

        # 绑定浏览器事件
        btn_back.clicked.connect(self.webview.back)
        btn_forward.clicked.connect(self.webview.forward)
        btn_reload.clicked.connect(self.webview.reload)
        self.webview.urlChanged.connect(lambda url: self.url_bar.setText(url.toString()))

        self.stack.addWidget(page)

    def init_empty_page(self, title):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_title = QLabel(title)
        lbl_title.setObjectName("EmptyTitle")
        lbl_desc = QLabel(f"{title} 模块暂未实现")
        lbl_desc.setObjectName("EmptyDesc")

        layout.addWidget(lbl_title, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(lbl_desc, 0, Qt.AlignmentFlag.AlignHCenter)

        self.stack.addWidget(page)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
