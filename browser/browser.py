import sys
import os
import json
import zipfile
import shutil
import requests

from PyQt5.QtCore import QUrl, Qt, pyqtSlot, QObject
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QToolBar, QAction, QLineEdit,
    QTabWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget,
    QFileDialog
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile, QWebEnginePage

EXT_DIR = "extensions"
SERVER_URL = "http://speed-previously-follow-sure.trycloudflare.com/extensions"

# Bridge for JS to call Python extension storage
class StorageBridge(QObject):
    def __init__(self, browser):
        super().__init__()
        self.browser = browser

    @pyqtSlot(str, str)
    def saveExtensionData(self, ext_name, data_json):
        ext = next((e for e in self.browser.extensions if e['name']==ext_name), None)
        if ext:
            storage_path = os.path.join(ext["path"], "storage.json")
            with open(storage_path, "w") as f:
                json.dump(json.loads(data_json), f, indent=4)

class Browser(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("James Browser Pro")
        self.setGeometry(100, 100, 1400, 900)

        os.makedirs(EXT_DIR, exist_ok=True)

        # Persistent profile
        self.profile = QWebEngineProfile("JamesProfile", self)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
        self.profile.setPersistentStoragePath("browser_data")
        self.profile.downloadRequested.connect(self.handle_download)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.setCentralWidget(self.tabs)

        self.extensions = self.load_extensions()
        self.js_bridge = StorageBridge(self)

        self.create_toolbar()
        self.add_new_tab("https://google.com")

    # ---------------- Extensions ----------------
    def load_extensions(self):
        extensions = []
        for folder in os.listdir(EXT_DIR):
            path = os.path.join(EXT_DIR, folder)
            manifest_path = os.path.join(path, "manifest.json")
            if os.path.exists(manifest_path):
                with open(manifest_path, "r") as f:
                    manifest = json.load(f)
                    manifest["path"] = path
                    extensions.append(manifest)
        return extensions

    def get_extension_storage(self, ext):
        storage_path = os.path.join(ext["path"], "storage.json")
        if not os.path.exists(storage_path):
            with open(storage_path, "w") as f:
                json.dump({}, f)
        with open(storage_path, "r") as f:
            return json.load(f)

    def inject_extensions(self, page):
        for ext in self.extensions:
            if not ext.get("enabled", True):
                continue
            if "inject_css" in ext:
                css_file = os.path.join(ext["path"], ext["inject_css"])
                if os.path.exists(css_file):
                    with open(css_file, "r") as f:
                        css = f.read()
                        page.runJavaScript(f"""
                        var style = document.createElement('style');
                        style.innerHTML = `{css}`;
                        document.head.appendChild(style);
                        """)
            if "inject_js" in ext:
                js_file = os.path.join(ext["path"], ext["inject_js"])
                if os.path.exists(js_file):
                    with open(js_file, "r") as f:
                        page.runJavaScript(f.read())
            storage_data = self.get_extension_storage(ext)
            page.runJavaScript(f"""
                window.ext_storage = {json.dumps(storage_data)};
                window.saveExtStorage = function(data) {{
                    qtBridge.saveExtensionData("{ext['name']}", JSON.stringify(data));
                }};
            """)

    # ---------------- Extension Management ----------------
    def install_extension_file(self, file_path):
        temp = "temp_ext"
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(temp)
        manifest_path = os.path.join(temp, "manifest.json")
        if not os.path.exists(manifest_path):
            shutil.rmtree(temp)
            return
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
        name = manifest.get("name", "unknown").replace(" ", "_")
        final_path = os.path.join(EXT_DIR, name)
        if os.path.exists(final_path):
            shutil.rmtree(final_path)
        shutil.move(temp, final_path)
        self.extensions = self.load_extensions()
        self.reload_all_tabs()

    def install_extension(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Install Extension", "", "Extension Files (*.ext)"
        )
        if file_path:
            self.install_extension_file(file_path)

    def toggle_extension(self, ext):
        manifest_path = os.path.join(ext["path"], "manifest.json")
        ext["enabled"] = not ext.get("enabled", True)
        with open(manifest_path, "w") as f:
            json.dump(ext, f, indent=4)
        self.extensions = self.load_extensions()
        self.reload_all_tabs()

    def uninstall_extension(self, ext):
        shutil.rmtree(ext["path"])
        self.extensions = self.load_extensions()
        self.reload_all_tabs()

    def reload_all_tabs(self):
        for i in range(self.tabs.count()):
            self.tabs.widget(i).reload()

    def open_extension_manager(self):
        manager = QMainWindow(self)
        manager.setWindowTitle("Extension Manager")
        manager.setGeometry(200, 200, 500, 400)

        central = QWidget()
        layout = QVBoxLayout()
        for ext in self.extensions:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{ext['name']} (v{ext.get('version','1.0')})"))

            toggle_btn = QPushButton("Disable" if ext.get("enabled", True) else "Enable")
            toggle_btn.clicked.connect(lambda _, e=ext: self.toggle_extension(e))
            row.addWidget(toggle_btn)

            remove_btn = QPushButton("Uninstall")
            remove_btn.clicked.connect(lambda _, e=ext: self.uninstall_extension(e))
            row.addWidget(remove_btn)

            layout.addLayout(row)

        install_btn = QPushButton("Install Extension (.ext)")
        install_btn.clicked.connect(self.install_extension)
        layout.addWidget(install_btn)

        store_btn = QPushButton("Open Extension Store")
        store_btn.clicked.connect(self.open_extension_store)
        layout.addWidget(store_btn)

        central.setLayout(layout)
        manager.setCentralWidget(central)
        manager.show()

    # ---------------- Extension Store with descriptions ----------------
    def open_extension_store(self):
        store_window = QMainWindow(self)
        store_window.setWindowTitle("Extension Store")
        store_window.setGeometry(250, 250, 400, 400)

        central = QWidget()
        layout = QVBoxLayout()

        def load_extensions():
            try:
                resp = requests.get(SERVER_URL)
                ext_list = resp.json()  # List of .ext filenames
            except:
                ext_list = []

            # Clear previous widgets
            for i in reversed(range(layout.count())):
                item = layout.itemAt(i)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    for j in reversed(range(item.layout().count())):
                        w = item.layout().itemAt(j).widget()
                        if w:
                            w.deleteLater()
                    layout.removeItem(item)

            # Refresh button
            refresh_btn = QPushButton("Refresh Store")
            refresh_btn.clicked.connect(load_extensions)
            layout.addWidget(refresh_btn)

            for ext_name in ext_list:
                try:
                    manifest_url = f"{SERVER_URL}/{ext_name}"
                    r = requests.get(manifest_url)
                    manifest_data = json.loads(r.content)
                    desc = manifest_data.get("description", "")
                except:
                    desc = ""

                row = QVBoxLayout()
                row.addWidget(QLabel(f"<b>{ext_name}</b>"))
                if desc:
                    row.addWidget(QLabel(desc))

                btn = QPushButton("Install")
                btn.clicked.connect(lambda _, name=ext_name: self.download_and_install(name))
                row.addWidget(btn)

                layout.addLayout(row)

        load_extensions()
        central.setLayout(layout)
        store_window.setCentralWidget(central)
        store_window.show()

    def download_and_install(self, ext_name):
        url = f"{SERVER_URL}/{ext_name}"
        resp = requests.get(url)
        if resp.status_code == 200:
            temp_path = os.path.join("temp_download.ext")
            with open(temp_path, "wb") as f:
                f.write(resp.content)
            self.install_extension_file(temp_path)
            os.remove(temp_path)

    # ---------------- Tabs ----------------
    def add_new_tab(self, url_or_page=None):
        if isinstance(url_or_page, str):
            page = QWebEnginePage(self.profile, self)
            page.setUrl(QUrl(url_or_page))
        else:
            page = url_or_page

        browser = QWebEngineView()
        browser.setPage(page)
        browser.loadFinished.connect(lambda: self.inject_extensions(page))
        page.createWindow = self.handle_new_window

        index = self.tabs.addTab(browser, "New Tab")
        self.tabs.setCurrentIndex(index)
        return browser

    def handle_new_window(self, window_type):
        new_page = QWebEnginePage(self.profile, self)
        self.add_new_tab(new_page)
        return new_page

    def close_tab(self, index):
        if self.tabs.count() > 1:
            self.tabs.removeTab(index)

    def current_browser(self):
        return self.tabs.currentWidget()

    # ---------------- Toolbar ----------------
    def create_toolbar(self):
        navbar = QToolBar()
        self.addToolBar(navbar)
        navbar.addAction("←", lambda: self.current_browser().back())
        navbar.addAction("→", lambda: self.current_browser().forward())
        navbar.addAction("⟳", lambda: self.current_browser().reload())
        navbar.addAction("+", lambda: self.add_new_tab("https://google.com"))
        navbar.addAction("🧩 Extensions", self.open_extension_manager)

        self.url_bar = QLineEdit()
        self.url_bar.returnPressed.connect(self.navigate_to_url)
        navbar.addWidget(self.url_bar)

    def navigate_to_url(self):
        url = self.url_bar.text()
        if not url.startswith("http"):
            url = "https://" + url
        self.current_browser().setUrl(QUrl(url))

    # ---------------- Downloads ----------------
    def handle_download(self, download):
        path, _ = QFileDialog.getSaveFileName(self, "Save File", download.path())
        if path:
            download.setPath(path)
            download.accept()

# ---------------- Run App ----------------
app = QApplication(sys.argv)
window = Browser()
window.show()
sys.exit(app.exec_())