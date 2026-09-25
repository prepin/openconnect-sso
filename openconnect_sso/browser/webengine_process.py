import asyncio
import json
import multiprocessing
import signal
import sys
from urllib.parse import urlparse

import attr
import structlog

try:
    from importlib.resources import read_text
except ImportError:
    from importlib_resources import read_text

from PyQt6.QtCore import QUrl, QTimer, pyqtSlot, Qt
from PyQt6.QtNetwork import QNetworkCookie, QNetworkProxy
from PyQt6.QtWebEngineCore import (
    QWebEngineLoadingInfo,
    QWebEngineScript,
    QWebEngineProfile,
    QWebEnginePage,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QWidget, QSizePolicy, QVBoxLayout

from openconnect_sso import config


app = None
profile = None
logger = structlog.get_logger("webengine")


@attr.s
class Url:
    url = attr.ib()


@attr.s
class LoadFailed:
    pass


@attr.s
class Credentials:
    credentials = attr.ib()


@attr.s
class StartupInfo:
    url = attr.ib()
    credentials = attr.ib()


@attr.s
class SetCookie:
    name = attr.ib()
    value = attr.ib()
    domain = attr.ib(default="")
    path = attr.ib(default="/")


class Process(multiprocessing.Process):
    def __init__(self, proxy, display_mode):
        super().__init__()

        self._commands = multiprocessing.Queue()
        self._states = multiprocessing.Queue()
        self.proxy = proxy
        self.display_mode = display_mode

    def authenticate_at(self, url, credentials):
        self._commands.put(StartupInfo(url, credentials))

    async def get_state_async(self):
        while self.is_alive():
            try:
                return self._states.get_nowait()
            except multiprocessing.queues.Empty:
                await asyncio.sleep(0.01)
        if not self.is_alive():
            raise EOFError()

    def run(self):
        # To work around funky GC conflicts with C++ code by ensuring QApplication terminates last
        global app
        global profile

        signal.signal(signal.SIGTERM, on_sigterm)
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        cfg = config.load()

        argv = sys.argv.copy()
        if self.display_mode == config.DisplayMode.HIDDEN:
            argv += ["-platform", "minimal"]
        app = QApplication(argv)
        profile = QWebEngineProfile("openconnect-sso")

        if self.proxy:
            parsed = urlparse(self.proxy)
            if parsed.scheme.startswith("socks5"):
                proxy_type = QNetworkProxy.Socks5Proxy
            elif parsed.scheme.startswith("http"):
                proxy_type = QNetworkProxy.HttpProxy
            else:
                raise ValueError("Unsupported proxy type", parsed.scheme)
            proxy = QNetworkProxy(proxy_type, parsed.hostname, parsed.port)

            QNetworkProxy.setApplicationProxy(proxy)

        # In order to make Python able to handle signals
        force_python_execution = QTimer()
        force_python_execution.start(200)

        def ignore():
            pass

        force_python_execution.timeout.connect(ignore)
        web = WebBrowser(cfg.auto_fill_rules, self._states.put, profile)

        startup_info = self._commands.get()
        logger.info("Browser started")

        logger.info("Loading page")

        web.authenticate_at(QUrl(startup_info.url), startup_info.credentials)

        web.show()
        rc = app.exec()

        logger.info("Exiting browser")
        return rc

    async def wait(self):
        while self.is_alive():
            await asyncio.sleep(0.01)
        self.join()


def on_sigterm(signum, frame):
    global profile
    logger.info("Terminate requested.")
    # Force flush cookieStore to disk. Without this hack the cookieStore may
    # not be synced at all if the browser lives only for a short amount of
    # time. Something is off with the call order of destructors as there is no
    # such issue in C++.

    # See: https://github.com/qutebrowser/qutebrowser/commit/8d55d093f29008b268569cdec28b700a8c42d761
    cookie = QNetworkCookie()
    profile.cookieStore().deleteCookie(cookie)

    # Give some time to actually save cookies
    exit_timer = QTimer(app)
    exit_timer.timeout.connect(QApplication.quit)
    exit_timer.start(1000)  # ms


class CustomWebEnginePage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if "[AutoFill]" in message or "[AutoFill] Error" in message:
            if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
                logger.error(
                    "JS Console", line=lineNumber, message=message, source=sourceID
                )
            elif (
                level
                == QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel
            ):
                logger.warning(
                    "JS Console", line=lineNumber, message=message, source=sourceID
                )
            else:
                logger.info(
                    "JS Console", line=lineNumber, message=message, source=sourceID
                )


class WebBrowser(QWebEngineView):
    def __init__(self, auto_fill_rules, on_update, profile):
        super().__init__()
        self._on_update = on_update
        self._auto_fill_rules = auto_fill_rules
        page = CustomWebEnginePage(profile, self)
        self.setPage(page)
        cookie_store = self.page().profile().cookieStore()
        cookie_store.cookieAdded.connect(self._on_cookie_added)
        self.page().loadFinished.connect(self._on_load_finished)
        self.page().loadingChanged.connect(self._on_loading_changed)

    def createWindow(self, type):
        if type == QWebEnginePage.WebDialog:
            self._popupWindow = WebPopupWindow(self.page().profile())
            return self._popupWindow.view()

    def authenticate_at(self, url, credentials):
        script_source = read_text(__package__, "user.js")
        script = QWebEngineScript()
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
        script.setSourceCode(script_source)
        self.page().scripts().insert(script)

        if credentials:
            logger.info("Initiating autologin")
            totp_selectors = [
                rule.selector
                for rules in self._auto_fill_rules.values()
                for rule in rules
                if rule.fill == "totp"
            ]
            if totp_selectors:
                self._credentials = credentials
                self._totp_check_script = get_totp_check_script(totp_selectors)
                self._totp_timer = QTimer(self)
                self._totp_timer.timeout.connect(self._check_totp_field)
                self._totp_timer.start(250)

            for url_pattern, rules in self._auto_fill_rules.items():
                script = QWebEngineScript()
                script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
                script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
                script.setSourceCode(
                    f"""
// ==UserScript==
// @include {url_pattern}
// ==/UserScript==

if (typeof window.autoFillFilledFields === 'undefined') {{
    window.autoFillFilledFields = new Set();
    window.autoFillButtonClicked = false;
    window.autoFillLastClickTime = 0;
}}

function autoFill() {{
    window.autoFillButtonClicked = false;
    {get_selectors(rules, credentials)}

    // Use longer delay if we recently clicked a button (page transitioning)
    var timeSinceLastClick = Date.now() - window.autoFillLastClickTime;
    var delay = (timeSinceLastClick < 2000) ? 2000 : 1000;
    setTimeout(autoFill, delay);
}}
autoFill();
"""
                )
                self.page().scripts().insert(script)

        self.load(QUrl(url))

    def _check_totp_field(self):
        self.page().runJavaScript(self._totp_check_script, self._fill_totp)

    def _fill_totp(self, selector):
        if selector:
            fill_totp(self.page(), selector, self._credentials)

    def _on_cookie_added(self, cookie):
        name = to_str(cookie.name())
        domain = cookie.domain()
        path = cookie.path() or "/"
        logger.debug("Cookie set", name=name, domain=domain, path=path)
        self._on_update(
            SetCookie(name, to_str(cookie.value()), domain=domain, path=path)
        )

    def _on_load_finished(self, success):
        if success:
            self._on_update(Url(self.page().url().toString()))

    def _on_loading_changed(self, info):
        if info.status() == QWebEngineLoadingInfo.LoadStatus.LoadFailedStatus:
            self._on_update(LoadFailed())


class WebPopupWindow(QWidget):
    def __init__(self, profile):
        super().__init__()
        self._view = QWebEngineView(self)

        super().setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        super().setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)

        layout = QVBoxLayout()
        super().setLayout(layout)
        layout.addWidget(self._view)

        self._view.setPage(QWebEnginePage(profile, self._view))

        self._view.titleChanged.connect(super().setWindowTitle)
        self._view.page().geometryChangeRequested.connect(
            self.handleGeometryChangeRequested
        )
        self._view.page().windowCloseRequested.connect(super().close)

    def view(self):
        return self._view

    @pyqtSlot("const QRect")
    def handleGeometryChangeRequested(self, newGeometry):
        self._view.setMinimumSize(newGeometry.width(), newGeometry.height())
        super().move(newGeometry.topLeft() - self._view.pos())
        super().resize(0, 0)
        super().show()


def to_str(qval):
    return bytes(qval).decode()


def get_selectors(rules, credentials):
    fill_statements = []
    click_statements = []
    totp_selectors = json.dumps(
        [rule.selector for rule in rules if rule.fill == "totp"]
    )

    for rule in rules:
        selector = json.dumps(rule.selector)
        if rule.action == "stop":
            fill_statements.append(
                f"""var elem = document.querySelector({selector}); if (elem) {{ return; }}"""
            )
        elif rule.fill:
            if rule.fill == "totp":
                continue
            cred_value = getattr(credentials, rule.fill, None)
            value = json.dumps(cred_value)
            if cred_value:
                fill_statements.append(
                    f"""(function() {{
    try {{
    var selectorKey = {selector};
    if (window.autoFillFilledFields.has(selectorKey)) return;

    var elem = document.querySelector(selectorKey);

    function isVisible(el) {{
        if (!el) return false;
        var style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        var parent = el.parentElement;
        while (parent && parent !== document.body) {{
            var parentStyle = window.getComputedStyle(parent);
            if (parentStyle.display === 'none' || parentStyle.visibility === 'hidden') return false;
            parent = parent.parentElement;
        }}
        return true;
    }}

    if (elem && !elem.value && isVisible(elem)) {{
        elem.focus();
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        nativeInputValueSetter.call(elem, {value});
        elem.dispatchEvent(new Event('input', {{bubbles: true}}));
        elem.dispatchEvent(new Event('change', {{bubbles: true}}));
        elem.dispatchEvent(new Event('blur', {{bubbles: true}}));
        if (elem.value) window.autoFillFilledFields.add(selectorKey);
    }}
    }} catch(e) {{ console.error('[AutoFill] Error:', {selector}, e); }}
}})();"""
                )
            else:
                logger.warning(
                    "Credential info not available",
                    type=rule.fill,
                    possibilities=dir(credentials),
                )
        elif rule.action == "click":
            click_statements.append(
                f"""(function() {{
    try {{
    if (window.autoFillButtonClicked) return;

    var pendingTotp = {totp_selectors}.some(function(totpSelector) {{
        var totpInput = document.querySelector(totpSelector);
        return totpInput && !totpInput.value && (totpInput.offsetWidth > 0 || totpInput.offsetHeight > 0 || totpInput.getClientRects().length > 0);
    }});
    if (pendingTotp) return;

    var totpRadio = Array.from(document.querySelectorAll('input[type=radio]')).find(function(r) {{
        var label = r.closest('label') || r.parentElement;
        return label && (label.textContent.includes('TOTP') || label.textContent.includes('Software TOTP'));
    }});
    if (totpRadio && !totpRadio.checked) totpRadio.click();

    var hasFilledField = Array.from(document.querySelectorAll('input:not([type=radio])')).some(function(inp) {{
        return inp.value && inp.value.length > 0;
    }});
    var hasCheckedRadio = Array.from(document.querySelectorAll('input[type=radio]')).some(function(radio) {{
        return radio.checked;
    }});
    if (!hasFilledField && !hasCheckedRadio) return;

    var buttons = Array.from(document.querySelectorAll({selector})).filter(function(b) {{
        return !b.disabled && b.textContent.trim() !== 'Back' && b.textContent.trim() !== 'Назад' && (b.offsetWidth > 0 || b.offsetHeight > 0 || b.getClientRects().length > 0);
    }});

    if (buttons.length > 0 && !buttons[0].disabled) {{
        window.autoFillButtonClicked = true;
        window.autoFillLastClickTime = Date.now();
        buttons[0].click();
    }}
    }} catch(e) {{ console.error('[AutoFill] Error:', {selector}, e); }}
}})();"""
            )
    result = "\n".join(fill_statements + click_statements)
    return result


def get_totp_check_script(selectors):
    return f"""(() => {{
    return {json.dumps(selectors)}.find(function(selector) {{
        var elem = document.querySelector(selector);
        if (!elem || elem.value) return false;
        var style = window.getComputedStyle(elem);
        return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && (elem.offsetWidth > 0 || elem.offsetHeight > 0 || elem.getClientRects().length > 0);
    }}) || null;
}})()"""


def fill_totp(page, selector, credentials):
    value = credentials.totp
    if not value:
        return

    page.runJavaScript(
        f"""(() => {{
    var elem = document.querySelector({json.dumps(selector)});
    if (!elem || elem.value) return;
    elem.focus();
    var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    nativeInputValueSetter.call(elem, {json.dumps(value)});
    elem.dispatchEvent(new Event('input', {{bubbles: true}}));
    elem.dispatchEvent(new Event('change', {{bubbles: true}}));
    elem.dispatchEvent(new Event('blur', {{bubbles: true}}));
}})()"""
    )
