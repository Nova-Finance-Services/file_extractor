"""HTTP route blueprints."""
from flask import Flask

from routes.chatbot import chatbot_bp
from routes.extraction import extraction_bp
from routes.health import health_bp
from routes.r2r import r2r_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(health_bp)
    app.register_blueprint(extraction_bp)
    app.register_blueprint(chatbot_bp)
    app.register_blueprint(r2r_bp)
