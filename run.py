import os
from flaskr import create_app

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '1') == '1'
    print(f"Starting SarkariSahayata server on http://127.0.0.1:{port} (Debug: {debug})...")
    app.run(host='0.0.0.0', port=port, debug=debug)
