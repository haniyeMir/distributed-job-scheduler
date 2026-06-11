from flask import Flask
from flask_socketio import SocketIO
from app.database import engine
from app.models import Base
from config import Config

socketio = SocketIO()


def create_app():
    app = Flask(__name__)

    Base.metadata.create_all(bind=engine)

    # Redis as message queue allows Celery workers (separate processes)
    # to emit WebSocket events to connected dashboard clients
    socketio.init_app(
        app,
        message_queue=Config.REDIS_URL,
        cors_allowed_origins="*",
        async_mode="threading",
    )

    from app.api.routes import api
    app.register_blueprint(api)

    from app.api.dashboard import dashboard
    app.register_blueprint(dashboard)

    return app