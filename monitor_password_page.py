#!/usr/bin/env python3
"""
Script to monitor the password page and extract the correct selector
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PyQt6.QtCore import QUrl, QTimer
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication


class PasswordPageMonitor(QWebEngineView):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Password Page Monitor")
        self.resize(1200, 800)

        self.page().loadFinished.connect(self.on_load_finished)

    def load_url(self, url):
        self.load(QUrl(url))

    def on_load_finished(self, success):
        if not success:
            return

        url = self.page().url().toString()

        if "2fa.mvideo.ru" in url:
            print(f"\n{'=' * 70}")
            print(f"Page: {url}")
            print(f"{'=' * 70}\n")

            # Check for all input fields
            js_code = """
            (function() {
                const inputs = [];
                document.querySelectorAll('input').forEach(input => {
                    if (input.offsetParent !== null) { // Only visible inputs
                        inputs.push({
                            name: input.name,
                            id: input.id,
                            type: input.type,
                            placeholder: input.placeholder,
                            class: input.className,
                            visible: true,
                            selector: input.id ? '#' + input.id : 
                                      input.name ? 'input[name="' + input.name + '"]' :
                                                      'input[type="' + input.type + '"]'
                        });
                    }
                });
                
                const buttons = [];
                document.querySelectorAll('button, input[type="submit"], input[type="button"]').forEach(btn => {
                    if (btn.offsetParent !== null) {
                        buttons.push({
                            text: (btn.textContent || btn.value || '').trim(),
                            type: btn.type,
                            id: btn.id,
                            name: btn.name,
                            selector: btn.id ? '#' + btn.id : 'button'
                        });
                    }
                });
                
                return {inputs, buttons, url: window.location.href};
            })();
            """

            self.page().runJavaScript(js_code, self.show_results)

    def show_results(self, data):
        if not data:
            return

        print(f"URL: {data['url']}\n")

        if data["inputs"]:
            print("VISIBLE INPUT FIELDS:")
            for i, inp in enumerate(data["inputs"], 1):
                print(f"  {i}. {inp['selector']}")
                if inp["name"]:
                    print(f"     name: {inp['name']}")
                if inp["id"]:
                    print(f"     id: {inp['id']}")
                if inp["type"]:
                    print(f"     type: {inp['type']}")
                if inp["placeholder"]:
                    print(f"     placeholder: {inp['placeholder']}")
                print()

        if data["buttons"]:
            print("VISIBLE BUTTONS:")
            for i, btn in enumerate(data["buttons"], 1):
                print(f"  {i}. {btn['selector']}")
                if btn["text"]:
                    print(f"     text: {btn['text']}")
                print()


def main():
    import signal

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)

    monitor = PasswordPageMonitor()
    monitor.show()

    print("\n🔍 Password Page Monitor")
    print("=" * 70)
    print("1. Enter your username manually and click 'Далее'")
    print("2. When the password page appears, I'll show you the correct selectors")
    print("=" * 70 + "\n")

    # Start at VPN URL
    monitor.load_url("https://mvpn.mvideo.ru")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
