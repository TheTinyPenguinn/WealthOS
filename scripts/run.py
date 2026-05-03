import os
import sys

# Force SSL fix for frozen app
if getattr(sys, 'frozen', False):
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()

from streamlit.web import cli as stcli

def resolve_path(path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, path)
    return os.path.join(os.path.abspath("."), path)

if __name__ == "__main__":
    # Point to your actual app code
    app_path = resolve_path("app/app.py")
    
    # Fake the command line arguments to start Streamlit
    sys.argv = [
        "streamlit",
        "run",
        app_path,
        "--global.developmentMode=false",
    ]
    
    # Launch!
    sys.exit(stcli.main())
