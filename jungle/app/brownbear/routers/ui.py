"""Dashboard pages (spec 001 §1.6).

Server-rendered shells; data arrives from the JSON API the same endpoints serve
to any other client, so the dashboard has no privileged path to the data and
nothing can be visible on a page but absent from the API.

Assets are local files, never a CDN: this stack is designed to run on a machine
with no internet.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

router = APIRouter(include_in_schema=False)


def _page(request: Request, template: str, page: str) -> HTMLResponse:
    return templates.TemplateResponse(request, template, {"page": page})


@router.get("/", response_class=HTMLResponse)
def overview(request: Request) -> HTMLResponse:
    return _page(request, "overview.html", "overview")


@router.get("/tokens", response_class=HTMLResponse)
def tokens(request: Request) -> HTMLResponse:
    return _page(request, "tokens.html", "tokens")


@router.get("/cache", response_class=HTMLResponse)
def cache(request: Request) -> HTMLResponse:
    return _page(request, "cache.html", "cache")


@router.get("/collections", response_class=HTMLResponse)
def collections(request: Request) -> HTMLResponse:
    return _page(request, "collections.html", "collections")


@router.get("/settings", response_class=HTMLResponse)
def settings(request: Request) -> HTMLResponse:
    return _page(request, "settings.html", "settings")
