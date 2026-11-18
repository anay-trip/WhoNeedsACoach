from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from whoneedsacoach.api.deps import get_registry, get_repo, require_user
from whoneedsacoach.api.schemas import ChallengeRequest, ConnectRequest, ProviderOut
from whoneedsacoach.integrations.registry import ProviderRegistry
from whoneedsacoach.store.repo import Repo

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("", response_model=list[ProviderOut])
def list_integrations(
    user: Annotated[dict, Depends(require_user)],
    repo: Annotated[Repo, Depends(get_repo)],
) -> list[ProviderOut]:
    rows = repo.list_provider_connections(user["id"])
    return [
        ProviderOut(provider=row["provider"], status=row["status"], connected_at=row["connected_at"])
        for row in rows
    ]


@router.post("/connect")
def connect(
    body: ConnectRequest,
    user: Annotated[dict, Depends(require_user)],
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
):
    adapter = registry.get(body.provider)
    if adapter is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown provider")
    result = adapter.connect(user["id"], {"email": body.email, "password": body.password})
    if result.get("status") == "error":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return result


@router.post("/challenge")
def challenge(
    body: ChallengeRequest,
    user: Annotated[dict, Depends(require_user)],
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
):
    adapter = registry.get(body.provider)
    if adapter is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown provider")
    result = adapter.complete_challenge(user["id"], body.challenge_id, body.code)
    if result.get("status") == "error":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return result


@router.delete("/{provider}")
def disconnect(
    provider: str,
    user: Annotated[dict, Depends(require_user)],
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
):
    adapter = registry.get(provider)
    if adapter is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown provider")
    return adapter.disconnect(user["id"])
