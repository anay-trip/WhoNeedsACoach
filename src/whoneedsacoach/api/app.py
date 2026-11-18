from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from whoneedsacoach.api.auth_routes import router as auth_router
from whoneedsacoach.api.integration_routes import router as integration_router
from whoneedsacoach.api.plan_routes import router as plan_router
from whoneedsacoach.integrations.registry import build_registry
from whoneedsacoach.store.repo import Repo
from whoneedsacoach.utils.config import CORS_ORIGINS, DB_PATH, TOKEN_ROOT


def create_app(
    *,
    db_path: Path | None = None,
    tokens_root: Path | None = None,
    registry=None,
) -> FastAPI:
    app = FastAPI(title="WhoNeedsACoach", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    path = Path(db_path or DB_PATH)
    root = Path(tokens_root or TOKEN_ROOT)
    repo = Repo(path)
    app.state.repo = repo
    app.state.tokens_root = root
    app.state.registry = registry if registry is not None else build_registry(repo, root)

    app.include_router(auth_router)
    app.include_router(integration_router)
    app.include_router(plan_router)

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


# Uvicorn entry: `uvicorn whoneedsacoach.api.app:app`
# Lazy so `from whoneedsacoach.api.app import create_app` does not open the default DB.
_app = None


def __getattr__(name: str):
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
