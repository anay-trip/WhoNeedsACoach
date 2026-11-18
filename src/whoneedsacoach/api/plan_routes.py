from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from whoneedsacoach.api.deps import get_repo, require_user
from whoneedsacoach.api.schemas import MeOut, PlanCreateRequest, PlanOut, ProviderOut
from whoneedsacoach.jobs.plan_build import run_plan_build, validate_plan_request
from whoneedsacoach.store.repo import Repo

router = APIRouter(tags=["plan"])


def _plan_out(plan: dict) -> PlanOut:
    return PlanOut(
        status=plan["status"],
        race=plan.get("race"),
        schedule=plan.get("schedule"),
        snapshot=plan.get("snapshot"),
        plan=plan.get("plan"),
        error_message=plan.get("error_message"),
        failed_at=plan.get("failed_at"),
        updated_at=plan.get("updated_at"),
    )


@router.get("/me", response_model=MeOut)
def me(
    user: Annotated[dict, Depends(require_user)],
    repo: Annotated[Repo, Depends(get_repo)],
) -> MeOut:
    integrations = [
        ProviderOut(provider=row["provider"], status=row["status"], connected_at=row["connected_at"])
        for row in repo.list_provider_connections(user["id"])
    ]
    plan = repo.get_plan(user["id"])
    return MeOut(
        id=user["id"],
        email=user["email"],
        display_name=user.get("display_name"),
        integrations=integrations,
        plan_status=plan["status"] if plan else None,
    )


@router.get("/plan", response_model=PlanOut)
def get_plan(
    user: Annotated[dict, Depends(require_user)],
    repo: Annotated[Repo, Depends(get_repo)],
) -> PlanOut:
    plan = repo.get_plan(user["id"])
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No plan")
    return _plan_out(plan)


@router.post("/plan", status_code=status.HTTP_202_ACCEPTED, response_model=PlanOut)
async def create_plan(
    body: PlanCreateRequest,
    background: BackgroundTasks,
    user: Annotated[dict, Depends(require_user)],
    repo: Annotated[Repo, Depends(get_repo)],
) -> PlanOut:
    try:
        normalized = validate_plan_request(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    plan = repo.upsert_plan_for_build(
        user["id"],
        race=normalized["race"],
        schedule=normalized["schedule"],
        snapshot=normalized["snapshot"],
        generation_id=normalized["generation_id"],
    )
    background.add_task(run_plan_build, repo, user["id"], normalized["generation_id"])
    return _plan_out(plan)
