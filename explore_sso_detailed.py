#!/usr/bin/env python3
"""
Enhanced script to explore SSO page and extract form field selectors
"""

import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from PyQt6.QtCore import QUrl, QTimer
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication
from openconnect_sso import config


class PageExplorer(QWebEngineView):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SSO Page Explorer")
        self.resize(1200, 800)

        self.page().loadFinished.connect(self.on_load_finished)
        self.current_url = None

    def load_url(self, url):
        self.current_url = url
        self.load(QUrl(url))

    def on_load_finished(self, success):
        if not success:
            print("Failed to load page")
            return

        url = self.page().url().toString()
        print(f"\n{'=' * 70}")
        print(f"Page loaded: {url}")
        print(f"{'=' * 70}\n")

        # Inject JavaScript to analyze form elements
        js_code = """
        (function() {
            const results = {
                url: window.location.href,
                inputs: [],
                buttons: [],
                forms: []
            };
            
            // Find all input fields
            document.querySelectorAll('input').forEach(input => {
                results.inputs.push({
                    type: input.type,
                    name: input.name,
                    id: input.id,
                    placeholder: input.placeholder,
                    class: input.className,
                    visible: input.offsetParent !== null,
                    selector: input.id ? `#${input.id}` : 
                              input.name ? `input[name="${input.name}"]` :
                              input.type ? `input[type="${input.type}"]` : 'input'
                });
            });
            
            // Find all buttons
            document.querySelectorAll('button, input[type="submit"], input[type="button"]').forEach(btn => {
                results.buttons.push({
                    text: btn.textContent || btn.value,
                    type: btn.type,
                    id: btn.id,
                    name: btn.name,
                    class: btn.className,
                    visible: btn.offsetParent !== null,
                    selector: btn.id ? `#${btn.id}` :
                              btn.name ? `button[name="${btn.name}"]` :
                              'button'
                });
            });
            
            // Find all forms
            document.querySelectorAll('form').forEach(form => {
                results.forms.push({
                    id: form.id,
                    name: form.name,
                    action: form.action,
                    method: form.method
                });
            });
            
            return results;
        })();
        """

        self.page().runJavaScript(js_code, self.print_results)

    def print_results(self, results):
        if not results:
            return

        print(f"URL: {results['url']}\n")

        if results["inputs"]:
            print("📝 INPUT FIELDS:")
            for i, inp in enumerate(results["inputs"], 1):
                if inp["visible"]:
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

        if results["buttons"]:
            print("🔘 BUTTONS:")
            for i, btn in enumerate(results["buttons"], 1):
                if btn["visible"]:
                    print(f"  {i}. {btn['selector']}")
                    if btn["text"]:
                        print(f"     text: {btn['text']}")
                    if btn["id"]:
                        print(f"     id: {btn['id']}")
                    if btn["type"]:
                        print(f"     type: {btn['type']}")
                    print()

        if results["forms"]:
            print("📋 FORMS:")
            for i, form in enumerate(results["forms"], 1):
                print(f"  {i}. {form['id'] or form['name'] or 'unnamed'}")
                if form["action"]:
                    print(f"     action: {form['action']}")
                if form["method"]:
                    print(f"     method: {form['method']}")
                print()

        print("\n💡 SUGGESTED AUTO-FILL RULES:")
        print("-" * 70)

        # Generate suggested rules
        for inp in results["inputs"]:
            if inp["visible"] and inp["type"] in [
                "text",
                "email",
                "password",
                "tel",
                "number",
            ]:
                fill_type = None
                if (
                    "login" in (inp["name"] or "").lower()
                    or "email" in (inp["type"] or "").lower()
                ):
                    fill_type = "username"
                elif (
                    "password" in (inp["name"] or "").lower()
                    or inp["type"] == "password"
                ):
                    fill_type = "password"
                elif (
                    "passcode" in (inp["name"] or "").lower()
                    or "totp" in (inp["name"] or "").lower()
                    or inp["type"] == "tel"
                ):
                    fill_type = "totp"

                if fill_type:
                    print(f"""
[[auto_fill_rules."https://2fa.mvideo.ru/*"]]
selector = "{inp["selector"]}"
fill = "{fill_type}"
""")

        for btn in results["buttons"]:
            if btn["visible"] and btn["type"] in ["submit", "button"]:
                print(f"""
[[auto_fill_rules."https://2fa.mvideo.ru/*"]]
selector = "{btn["selector"]}"
action = "click"
""")

        print("\n" + "=" * 70)
        print("Press Ctrl+C to exit or wait for next page load...")
        print("=" * 70 + "\n")


def main():
    import signal

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)

    explorer = PageExplorer()
    explorer.show()

    # Load the VPN URL which should redirect to SSO
    explorer.load_url("https://mvpn.mvideo.ru")

    print("\n🔍 SSO Page Explorer Started")
    print("=" * 70)
    print("The browser will navigate through the SSO flow.")
    print("Please manually enter your credentials to proceed through each step.")
    print("I'll analyze each page and show you the correct selectors.\n")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
