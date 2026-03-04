#!/usr/bin/env python3
"""Monitor auto-fill behavior on real mvideo.ru page"""

import sys
from PyQt6.QtCore import QUrl, QTimer
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget


class CustomWebEnginePage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        # Print all AutoFill messages
        if (
            "[AutoFill]" in message
            or "[VisibilityTest]" in message
            or "Monitor]" in message
        ):
            print(f"{message}")


app = QApplication(sys.argv)
view = QWebEngineView()
page = CustomWebEnginePage(view)
view.setPage(page)


# Inject monitoring script after page loads
def on_load_finished():
    print("[Monitor] Page loaded, starting monitoring...")

    # Monitor DOM changes and field values every 500ms
    monitor_script = """
    (function() {
        var lastValues = {};
        
        function checkFields() {
            var selectors = [
                'input[name=Login]',
                'input[name=WindowsPassword]', 
                'input[name=GoogleOtp]'
            ];
            
            function isVisible(el) {
                if (!el) return false;
                var style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                    return false;
                }
                var parent = el.parentElement;
                while (parent && parent !== document.body) {
                    var parentStyle = window.getComputedStyle(parent);
                    if (parentStyle.display === 'none' || parentStyle.visibility === 'hidden') {
                        return false;
                    }
                    parent = parent.parentElement;
                }
                return true;
            }
            
            selectors.forEach(function(sel) {
                var elem = document.querySelector(sel);
                if (elem) {
                    var visible = isVisible(elem);
                    var currentValue = elem.value || '';
                    var lastValue = lastValues[sel] || '';
                    
                    if (currentValue !== lastValue || visible !== (lastValues[sel + '_visible'] || false)) {
                        console.log('[Monitor]', sel, '| visible:', visible, '| value:', currentValue.substring(0, 20) + (currentValue.length > 20 ? '...' : ''), '| changed:', currentValue !== lastValue);
                        lastValues[sel] = currentValue;
                        lastValues[sel + '_visible'] = visible;
                    }
                }
            });
        }
        
        setInterval(checkFields, 500);
        console.log('[Monitor] Started monitoring field changes every 500ms');
    })();
    """

    view.page().runJavaScript(monitor_script)


view.loadFinished.connect(on_load_finished)

# Load the real mvideo.ru page
print("[Monitor] Loading https://mvpn.mvideo.ru ...")
print("[Monitor] Watch for field value changes...")
view.load(QUrl("https://mvpn.mvideo.ru"))

window = QWidget()
layout = QVBoxLayout()
layout.addWidget(view)
window.setLayout(layout)
window.resize(1024, 768)
window.show()

# Auto-close after 60 seconds
QTimer.singleShot(60000, app.quit)

sys.exit(app.exec())
