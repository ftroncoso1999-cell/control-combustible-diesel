import os
import socket
import sys
import threading
import time
from pathlib import Path

import webview


PORT = 8501
URL = f"http://127.0.0.1:{PORT}"


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return base_dir()


BASE_DIR = base_dir()
RESOURCE_DIR = resource_dir()
APP_PATH = RESOURCE_DIR / "app.py"


def wait_for_port(host: str, port: int, timeout: int = 90) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.8)
    return False


def run_streamlit_internal():
    os.chdir(str(RESOURCE_DIR))

    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"

    import streamlit.web.cli as stcli

    sys.argv = [
        "streamlit",
        "run",
        str(APP_PATH),
        "--server.headless=true",
        "--server.address=127.0.0.1",
        f"--server.port={PORT}",
        "--browser.gatherUsageStats=false",
        "--server.enableCORS=false",
        "--server.enableXsrfProtection=false",
    ]

    try:
        stcli.main()
    except SystemExit:
        pass


def main():
    if not APP_PATH.exists():
        webview.create_window(
            "Error - Control Combustible",
            html=f"<h2>No se encontró app.py</h2><pre>{APP_PATH}</pre>",
            width=900,
            height=500,
        )
        webview.start()
        return

    server_thread = threading.Thread(target=run_streamlit_internal, daemon=True)
    server_thread.start()

    if not wait_for_port("127.0.0.1", PORT, timeout=90):
        webview.create_window(
            "Error - Control Combustible",
            html="<h2>No fue posible iniciar la aplicación</h2><p>Revise que el puerto 8501 no esté ocupado.</p>",
            width=900,
            height=500,
        )
        webview.start()
        return

    webview.create_window(
        title="Control de Combustible Diesel",
        url=URL,
        width=1400,
        height=900,
        min_size=(1100, 700),
        resizable=True,
        fullscreen=False,
        confirm_close=True,
    )
    webview.start(debug=False)


if __name__ == "__main__":
    main()
