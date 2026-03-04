#!/usr/bin/env python3
"""Test visibility checks in Qt WebEngine"""

import sys
from PyQt6.QtCore import QUrl
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

# Load the test file
import os

test_file = os.path.join(os.path.dirname(__file__), "test_visibility.html")
view.load(QUrl.fromLocalFile(test_file))

window = QWidget()
layout = QVBoxLayout()
layout.addWidget(view)
window.setLayout(layout)
window.resize(800, 600)
window.show()

sys.exit(app.exec())
