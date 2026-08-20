"""Serving the frontend HTML dashboard page."""

from fastapi import APIRouter
from fastapi.responses import FileResponse
import os

router = APIRouter(tags=["Dashboard"])

@router.get("/")
def get_dashboard():
    """Serves the static index HTML page."""
    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(current_dir, "static", "dashboard.html")
    return FileResponse(file_path)
