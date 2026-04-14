import os
import sys
from pathlib import Path

from werkzeug.serving import run_simple

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parent
for candidate in [str(ROOT_DIR), str(BACKEND_DIR)]:
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

if "MAIN_APP_DB_PATH" not in os.environ and os.getenv("BOOK_DB_PATH"):
    os.environ["MAIN_APP_DB_PATH"] = os.getenv("BOOK_DB_PATH", "")

from server import app as main_app  # noqa: E402

application = main_app


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    run_simple(
        hostname="0.0.0.0",
        port=port,
        application=application,
        use_debugger=False,
        use_reloader=False,
        threaded=True,
    )
