"""
Nova Flask worker: file extraction, chatbot document processing, R2R accounting agent.
"""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from flask import Flask

from fileExtraction import CONFIG
from routes import register_blueprints
from routes.limiter import limiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    flask_app = Flask(__name__)
    flask_app.config["MAX_CONTENT_LENGTH"] = CONFIG["MAX_FILE_SIZE"] * 2
    limiter.init_app(flask_app)
    register_blueprints(flask_app)
    return flask_app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    logger.info("Starting Flask worker on port %s (debug=%s)", port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug)
