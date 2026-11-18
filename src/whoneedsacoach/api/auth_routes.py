from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from whoneedsacoach.auth.passwords import hash_password, verify_password
from whoneedsacoach.auth.tokens import (
    REFRESH_COOKIE,
    REFRESH_PATH,
    create_access_token,
    hash_token,
    new_refresh_token,
)
from whoneedsacoach.api.deps import get_repo
from whoneedsacoach.api.schemas import AccessTokenResponse, LoginRequest, RegisterRequest
from whoneedsacoach.store.repo import Repo
from whoneedsacoach.utils.config import AUTH_ACCESS_TTL_SECONDS, AUTH_COOKIE_SECURE

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite="lax",
        path=REFRESH_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE, path=REFRESH_PATH)


def _issue(repo: Repo, user_id: int, response: Response) -> AccessTokenResponse:
    refresh = new_refresh_token()
    repo.store_refresh_token(user_id, hash_token(refresh))
    _set_refresh_cookie(response, refresh)
    return AccessTokenResponse(
        access_token=create_access_token(user_id),
        expires_in=AUTH_ACCESS_TTL_SECONDS,
    )


@router.post("/register", response_model=AccessTokenResponse)
def register(
    body: RegisterRequest,
    response: Response,
    repo: Annotated[Repo, Depends(get_repo)],
) -> AccessTokenResponse:
    if repo.get_user_by_email(body.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = repo.create_user(
        email=str(body.email),
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    return _issue(repo, user["id"], response)


@router.post("/login", response_model=AccessTokenResponse)
def login(
    body: LoginRequest,
    response: Response,
    repo: Annotated[Repo, Depends(get_repo)],
) -> AccessTokenResponse:
    user = repo.get_user_by_email(str(body.email))
    if user is None or not verify_password(body.password, user.get("password_hash")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return _issue(repo, user["id"], response)


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh(
    request: Request,
    response: Response,
    repo: Annotated[Repo, Depends(get_repo)],
) -> AccessTokenResponse:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")
    row = repo.get_refresh_token(hash_token(token))
    if row is None or row["revoked_at"] is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user = repo.get_user(row["user_id"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    # No rotation: same cookie stays valid; only mint a new access JWT.
    return AccessTokenResponse(
        access_token=create_access_token(user["id"]),
        expires_in=AUTH_ACCESS_TTL_SECONDS,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    repo: Annotated[Repo, Depends(get_repo)],
) -> Response:
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        repo.revoke_refresh_token(hash_token(token))
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
