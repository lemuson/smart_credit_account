from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select

from app.auth.dependencies import CurrentUser
from app.common import DB, fail
from app.scoring.models import ScoringWhatIf
from app.scoring.schemas import (
    AssessmentCreate,
    AssessmentResponse,
    Problem,
    WhatIfCreate,
    WhatIfResponse,
)
from app.scoring.service import (
    assessment_for,
    create_assessment,
    create_what_if,
    identity,
)


def request_id_header(
    request_id: Annotated[UUID | None, Header(alias="X-Request-ID")] = None,
):
    return request_id


router = APIRouter(
    prefix="/scoring",
    tags=["ML Scoring"],
    dependencies=[Depends(request_id_header)],
    responses={
        status: {
            "description": description,
            "content": {"application/problem+json": {"schema": Problem.model_json_schema()}},
        }
        for status, description in {
            401: "Missing or invalid credentials",
            403: "Insufficient scoring scope",
            404: "Resource not found",
            409: "Version or idempotency conflict",
            422: "Invalid or unsupported input",
            503: "Scoring runtime unavailable",
        }.items()
    },
)
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


@router.post(
    "/assessments",
    operation_id="createScoringAssessment",
    status_code=201,
    response_model=AssessmentResponse,
    responses={200: {"model": AssessmentResponse, "description": "Idempotent replay"}},
)
def assess(
    data: AssessmentCreate,
    key: IdempotencyKey,
    request: Request,
    response: Response,
    db: DB,
    user: CurrentUser,
):
    result, replayed = create_assessment(db, user, data, key, request)
    response.status_code = 200 if replayed else 201
    response.headers["Location"] = f"/api/v1/scoring/assessments/{result['assessment_id']}"
    return result


@router.get(
    "/assessments/{assessment_id}",
    response_model=AssessmentResponse,
    operation_id="getScoringAssessment",
)
def read(
    assessment_id: UUID,
    db: DB,
    user: CurrentUser,
    response: Response,
    what_if_id: UUID | None = None,
):
    org = identity(db, user)
    assessment = assessment_for(db, assessment_id, org, user)
    result = {**assessment.response, "selected_what_if": None}
    if what_if_id:
        alternative = db.scalar(
            select(ScoringWhatIf).where(
                ScoringWhatIf.id == str(what_if_id),
                ScoringWhatIf.organization_id == org,
                ScoringWhatIf.assessment_id == assessment.id,
            )
        )
        if alternative is None:
            fail(404, "SCORING_NOT_FOUND")
        result["selected_what_if"] = alternative.response
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post(
    "/assessments/{assessment_id}/what-if",
    operation_id="createScoringWhatIf",
    status_code=201,
    response_model=WhatIfResponse,
    responses={200: {"model": WhatIfResponse, "description": "Idempotent replay"}},
)
def what_if(
    assessment_id: UUID,
    data: WhatIfCreate,
    key: IdempotencyKey,
    request: Request,
    response: Response,
    db: DB,
    user: CurrentUser,
):
    result, replayed = create_what_if(db, user, assessment_id, data, key, request)
    response.status_code = 200 if replayed else 201
    return result
