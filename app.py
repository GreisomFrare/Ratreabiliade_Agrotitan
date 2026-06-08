import os
from flask import Flask, send_from_directory
from flask_cors import CORS
from routes.trace import bp as trace_bp
from routes.descduprec import bp as descduprec_bp

BASE_DIR = os.path.dirname(__file__)
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")


def create_app():
    app = Flask(__name__, static_folder=None)
    CORS(app)

    app.register_blueprint(trace_bp)
    app.register_blueprint(descduprec_bp)

    @app.route("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.route("/assets/<path:filename>")
    def assets(filename):
        return send_from_directory(os.path.join(FRONTEND_DIR, "assets"), filename)

    return app


if __name__ == "__main__":
    import json
    cfg = json.load(open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8"))
    porta = cfg.get("server", {}).get("porta", 5001)
    app = create_app()
    app.run(host="0.0.0.0", port=porta, debug=True)
