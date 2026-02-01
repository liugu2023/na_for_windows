import sys
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QStackedWidget,
                             QLineEdit, QFrame, QSizePolicy)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl, Qt, QSize
from PyQt6.QtGui import QIcon, QFont, QAction

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
    padding: 10px;
    text-align: center;
    color: #57606a;
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

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("V-OS 部署工具")
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
        self.sidebar.setFixedWidth(68)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 20, 10, 20)
        sidebar_layout.setSpacing(10)

        # Logo
        logo_label = QLabel("V")
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label.setStyleSheet("background-color: #24292f; color: white; border-radius: 8px; font-weight: bold; font-size: 20px;")
        logo_label.setFixedSize(40, 40)
        sidebar_layout.addWidget(logo_label, 0, Qt.AlignmentFlag.AlignHCenter)

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

    def create_sidebar_btn(self, icon_text, tooltip):
        btn = QPushButton(icon_text)
        btn.setObjectName("SidebarBtn")
        btn.setToolTip(tooltip)
        btn.setCheckable(True)
        btn.setFixedSize(44, 44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # 设置字体大小以显示 Emoji
        font = QFont()
        font.setPointSize(16)
        btn.setFont(font)

        # 绑定点击事件 (需要配合 lambda 传递 index，这里简单根据 tooltip 判断)
        index_map = {
            "项目概览": 0, "应用浏览器": 1, "运行日志": 2,
            "文件管理": 3, "系统设置": 4
        }
        if tooltip in index_map:
            btn.clicked.connect(lambda: self.switch_tab(index_map[tooltip]))

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

        # 标题栏
        header = QLabel("项目概览")
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #24292f; margin: 20px;")
        layout.addWidget(header)

        # 内容
        content = QLabel("右侧内容区域留空\n等待具体功能模块嵌入")
        content.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.setStyleSheet("color: #8b949e; font-size: 16px;")
        layout.addWidget(content)

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
        # 加载一个默认页面
        self.webview.setUrl(QUrl("https://mirrors.aliyun.com/alpine/"))
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
