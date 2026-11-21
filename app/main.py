from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pathlib import Path
app = FastAPI()
@app.get("/", response_class=HTMLResponse)
def home():
html_file = Path("index.html")
if html_file.exists():
return html_file.read_text(encoding="utf-8")
return "<h1>AI Video Studio Running</h1>"
