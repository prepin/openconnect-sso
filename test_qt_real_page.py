#!/usr/bin/env python3
"""Test visibility checks in Qt WebEngine with real mvideo.ru page"""

import sys
import time
from PyQt6.QtCore import QUrl, QTimer
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget


class CustomWebEnginePage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        print(f"[Qt Console] {message}")


app = QApplication(sys.argv)
view = QWebEngineView()
page = CustomWebEnginePage(view)
view.setPage(page)


# Inject visibility test script after page loads
def on_load_finished():
    print("[Test] Page loaded, injecting visibility test script...")

    script = """
    // Use the exact same visibility check as in webengine_process.py
    function isVisible(el) {
        if (!el) return false;
        var style = window.getComputedStyle(el);
        console.log('[VisibilityTest] Element:', el.name || el.id, 'display:', style.display, 'visibility:', style.visibility, 'opacity:', style.opacity);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
            return false;
        }
        var parent = el.parentElement;
        while (parent && parent !== document.body) {
            var parentStyle = window.getComputedStyle(parent);
            console.log('[VisibilityTest]   Parent:', parent.id || parent.className, 'display:', parentStyle.display, 'visibility:', parentStyle.visibility);
            if (parentStyle.display === 'none' || parentStyle.visibility === 'hidden') {
                return false;
            }
            parent = parent.parentElement;
        }
        return true;
    }
    
    // Use exact same selectors as in config.toml
    var selectors = [
        'input[name=Login]',
        'input[name=WindowsPassword]', 
        'input[name=GoogleOtp]'
    ];
    
    console.log('[VisibilityTest] ========== QT WEBENGINE CHECKING VISIBILITY ==========');
    selectors.forEach(function(sel) {
        var elem = document.querySelector(sel);
        var visible = isVisible(elem);
        console.log('[VisibilityTest] RESULT - Selector:', sel, 'visible:', visible, 'elem exists:', !!elem);
    });
    console.log('[VisibilityTest] =======================================');
    """

    view.page().runJavaScript(script)


view.loadFinished.connect(on_load_finished)

# Load the real mvideo.ru page
print("[Test] Loading https://mvpn.mvideo.ru ...")
view.load(QUrl("https://mvpn.mvideo.ru"))

window = QWidget()
layout = QVBoxLayout()
layout.addWidget(view)
window.setLayout(layout)
window.resize(1024, 768)
window.show()

# Auto-close after 30 seconds
QTimer.singleShot(30000, app.quit)

sys.exit(app.exec())
