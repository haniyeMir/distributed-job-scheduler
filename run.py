from app import create_app, socketio
from app.websocket.events import start_background_pusher

app = create_app()

if __name__ == "__main__":
    start_background_pusher(socketio)
    socketio.run(
        app,
        debug=False,
        host="0.0.0.0",
        port=5000,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )