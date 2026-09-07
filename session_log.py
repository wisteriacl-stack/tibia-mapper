from datetime import datetime

from app_paths import RUNTIME_ROOT

LOG_DIR = RUNTIME_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


def log_event(message):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {message}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def get_log_path():
    return str(LOG_PATH)
