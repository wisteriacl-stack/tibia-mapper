from __future__ import annotations

import threading
import time
import webbrowser

from app import app
from session_log import log_event

HOST = "127.0.0.1"
PORT = 5000
URL = f"http://{HOST}:{PORT}"


def _open_browser():
    time.sleep(1.2)
    try:
        webbrowser.open(URL)
    except Exception as exc:
        log_event(f"No se pudo abrir el navegador automáticamente: {exc}")


if __name__ == "__main__":
    threading.Thread(target=_open_browser, daemon=True).start()
    log_event(f"Tibia Mapper disponible en {URL}")
    app.run(host=HOST, port=PORT, debug=False, threaded=True, use_reloader=False)
