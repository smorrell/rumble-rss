import atexit
import sys
from datetime import datetime
from pathlib import Path


class TeeStream:
    def __init__(self, console, log_file):
        self.console = console
        self.log_file = log_file

    def write(self, text):
        self.console.write(text)
        self.log_file.write(text)
        return len(text)

    def flush(self):
        self.console.flush()
        self.log_file.flush()

    def __getattr__(self, name):
        return getattr(self.console, name)


def configure_script_logging(log_filename):
    log_file = Path(__file__).with_name(log_filename).open(
        "w", encoding="utf-8", buffering=1
    )
    sys.stdout = TeeStream(sys.stdout, log_file)
    sys.stderr = TeeStream(sys.stderr, log_file)

    print(
        f"\n===== Run started "
        f"{datetime.now().astimezone().isoformat(timespec='seconds')} ====="
    )
    atexit.register(
        lambda: print(
            f"===== Run ended "
            f"{datetime.now().astimezone().isoformat(timespec='seconds')} ====="
        )
    )
