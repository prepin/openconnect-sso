#!/usr/bin/env python3
"""
Monitor all three SSO steps and capture field selectors
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PyQt6.QtCore import QUrl, QTimer
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication


class StepMonitor(QWebEngineView):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SSO Step Monitor")
        self.resize(1200, 800)
        self.step_count = 0

        self.page().loadFinished.connect(self.on_load_finished)

    def load_url(self, url):
        self.load(QUrl(url))

    def on_load_finished(self, success):
        if not success:
            return

        url = self.page().url().toString()

        if "2fa.mvideo.ru" in url and "SsoService" not in url:
            self.step_count += 1
            print(f"\n{'=' * 70}")
            print(f"STEP {self.step_count}: {url[:80]}...")
            print(f"{'=' * 70}\n")

            # Check for all input fields
            js_code = """
            (function() {
                const inputs = [];
                document.querySelectorAll('input').forEach(input => {
                    if (input.offsetParent !== null) {
                        inputs.push({
                            name: input.name,
                            id: input.id,
                            type: input.type,
                            placeholder: input.placeholder,
                            value: input.value ? '(has value)' : '(empty)',
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

        if data["inputs"]:
            print("📝 VISIBLE INPUT FIELDS:")
            for i, inp in enumerate(data["inputs"], 1):
                print(f"  {i}. {inp['selector']}")
                print(f"     name: {inp['name'] or '(none)'}")
                print(f"     id: {inp['id'] or '(none)'}")
                print(f"     type: {inp['type']}")
                print(f"     placeholder: {inp['placeholder'] or '(none)'}")
                print(f"     value: {inp['value']}")
                print()
        else:
            print("📝 No visible input fields found\n")

        if data["buttons"]:
            print("🔘 VISIBLE BUTTONS:")
            for i, btn in enumerate(data["buttons"], 1):
                print(f"  {i}. {btn['selector']}")
                print(f"     text: '{btn['text']}'")
                print()
        else:
            print("🔘 No visible buttons found\n")


def main():
    import signal

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)

    monitor = StepMonitor()
    monitor.show()

    print("\n🔍 SSO Step Monitor")
    print("=" * 70)
    print("This will monitor each step of the SSO process.")
    print("Please complete all 3 steps manually:")
    print("  1. Enter username")
    print("  2. Enter password")
    print("  3. Enter TOTP")
    print("=" * 70 + "\n")

    # Start at VPN URL
    monitor.load_url("https://mvpn.mvideo.ru")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
