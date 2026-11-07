"""Start the backend: python run.py  (binds to 127.0.0.1 only - the API has no login)."""
import uvicorn

from app.core.config import API_PORT
from app.main import app

if __name__ == "__main__":
    # timeout_graceful_shutdown: open dashboard WebSockets would otherwise keep shutdown waiting forever
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=API_PORT, log_level="info", timeout_graceful_shutdown=5))
    app.state.server = server  # lets POST /api/system/shutdown stop gracefully
    server.run()
