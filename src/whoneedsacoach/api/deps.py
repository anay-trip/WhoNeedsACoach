from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from whoneedsacoach.auth.tokens import decode_access_token
from whoneedsacoach.integrations.registry import ProviderRegistry
from whoneedsacoach.store.repo import Repo

bearer = HTTPBearer(auto_error=False)


def get_repo(request: Request) -> Repo:
    return request.app.state.repo


def get_registry(request: Request) -> ProviderRegistry:
    return request.app.state.registry


def get_tokens_root(request: Request) -> Path:
    return request.app.state.tokens_root


async def require_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    repo: Annotated[Repo, Depends(get_repo)],
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    user = repo.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    request.state.user = user
    return user
