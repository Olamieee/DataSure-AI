"""Development entry point: flask / python run.py"""
from datasure import create_app

# flask CLI uses these when invoking `flask run`.
app = create_app("development")

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
