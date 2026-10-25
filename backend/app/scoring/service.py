import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from threading import BoundedSemaphore

from ml_scoring.inference_schema import CreditApplication
from ml_scoring.local_inference import UnsupportedInputRangeError
from ml_scoring.what_if import compare_applications
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.applications.models import Application, AuditEvent
from app.auth.models import Role
from app.common import fail
from app.database import new_id, now
from app.profiles.models import Profile
from app.scoring.models import ScoringAssessment, ScoringRequest, ScoringWhatIf


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def identity(db, user, write=False):
    # В текущей модели одна организация — один профиль клиента. У сотрудников нет tenant membership.
    if user.role != Role.CLIENT:
        fail(403, "SCORING_SCOPE_REQUIRED", scope="scoring:write" if write else "scoring:read")
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is None:
        fail(404, "SCORING_NOT_FOUND")
    return profile.id


def application_for(db, application_id, user, lock=False):
    query = select(Application).where(
        Application.id == str(application_id), Application.client_id == user.id
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    obj = db.scalar(query)
    if obj is None:
        fail(404, "SCORING_NOT_FOUND")
    return obj


def assessment_for(db, assessment_id, organization_id, user):
    obj = db.scalar(
        select(ScoringAssessment).where(
            ScoringAssessment.id == str(assessment_id),
            ScoringAssessment.organization_id == organization_id,
        )
    )
    if obj is None:
        fail(404, "SCORING_NOT_FOUND")
    application_for(db, obj.application_id, user)
    return obj


def feature_snapshot(application, as_of):
    try:
        registered = date.fromisoformat(application.company["registration_date"])
        if registered > as_of:
            raise ValueError("future registration date")
        months = (as_of.year - registered.year) * 12 + as_of.month - registered.month
        months -= as_of.day < registered.day
        revenue = application.financials["annual_revenue"]
        if isinstance(revenue, bool):
            raise ValueError("invalid revenue")
        revenue = Decimal(str(revenue))
        if not revenue.is_finite():
            raise ValueError("invalid revenue")
        values = {
            "annual_revenue": float(revenue),
            "credit_history": application.financials["credit_history"],
            "business_age_months": months,
            "loan_amount": float(application.amount),
            "has_collateral": application.financials["has_collateral"],
            "loan_term_months": application.term_months,
        }
        return CreditApplication.model_validate(values).model_dump(exclude={"age"})
    except (KeyError, TypeError, ValueError, InvalidOperation):
        fail(
            422,
            "SCORING_INVALID_INPUT",
            errors=[
                {"field": "application", "message": "Missing or invalid saved scoring features"}
            ],
        )


def runtime(request):
    service = request.app.state.scoring_service
    if service is None:
        fail(503, "SCORING_UNAVAILABLE")
    return service


INFERENCE_SLOTS = BoundedSemaphore(4)


def infer(operation):
    if not INFERENCE_SLOTS.acquire(blocking=False):
        fail(503, "SCORING_BUSY")
    try:
        return operation()
    except UnsupportedInputRangeError as exc:
        errors = [{k: v for k, v in issue.items() if k != "value"} for issue in exc.issues]
        fail(422, "SCORING_UNSUPPORTED_RANGE", errors=errors)
    except ValidationError as exc:
        fail(
            422,
            "SCORING_INVALID_INPUT",
            errors=[
                {"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()
            ],
        )
    except (ArithmeticError, ValueError, TypeError):
        fail(503, "SCORING_UNAVAILABLE")
    finally:
        INFERENCE_SLOTS.release()


def score_view(result):
    return {
        "name": result.score.name,
        "value": result.score.probability,
        "display_percent": result.score.display_percent,
    }


def snapshot_view(result):
    return {
        "score": score_view(result),
        "factors": [factor.model_dump(mode="json") for factor in result.factors],
    }


def replay(db, org, user_id, key, digest):
    obj = db.scalar(
        select(ScoringRequest).where(
            ScoringRequest.organization_id == org,
            ScoringRequest.user_id == user_id,
            ScoringRequest.key == str(key),
        )
    )
    if obj:
        if obj.fingerprint != digest:
            fail(409, "IDEMPOTENCY_KEY_REUSED")
        return obj.response
    return None


def persist(db, org, user, key, digest, obj, response, application, request_id):
    try:
        with db.begin_nested():
            db.add(obj)
            db.flush()
            db.add(
                ScoringRequest(
                    organization_id=org,
                    user_id=user.id,
                    key=str(key),
                    fingerprint=digest,
                    response=response,
                )
            )
            db.add(
                AuditEvent(
                    application_id=application.id,
                    actor_id=user.id,
                    action="scoring.what_if"
                    if isinstance(obj, ScoringWhatIf)
                    else "scoring.assessment",
                    to_status=application.status,
                    details={"resource_id": obj.id, "request_id": str(request_id)},
                )
            )
            db.flush()
    except IntegrityError:
        previous = replay(db, org, user.id, key, digest)
        if previous is None:
            raise
        return previous, True
    return response, False


def create_assessment(db, user, data, key, request):
    org = identity(db, user, write=True)
    application = application_for(db, data.application_id, user)
    digest = fingerprint({"operation": "assessment", **data.model_dump(mode="json")})
    previous = replay(db, org, user.id, key, digest)
    if previous is not None:
        return previous, True
    version = application.version
    if (
        data.expected_application_version is not None
        and data.expected_application_version != version
    ):
        fail(409, "APPLICATION_VERSION_CONFLICT")
    timestamp = now()
    features = feature_snapshot(application, timestamp.date())
    # Освобождаем read transaction до CPU inference; повторная проверка идёт под row lock.
    db.rollback()
    result = infer(lambda: runtime(request).score(features))
    application = application_for(db, data.application_id, user, lock=True)
    if application.version != version:
        fail(409, "APPLICATION_VERSION_CONFLICT")
    diagnostics = result.diagnostics
    assessment_id = new_id()
    response = {
        "assessment_id": assessment_id,
        "application_id": application.id,
        "application_version": version,
        "schema_version": result.schema_version,
        "status": "completed",
        "model": result.model.model_dump(mode="json"),
        "demonstration_only": True,
        "score": score_view(result),
        "explanation": {
            "baseline": {
                "method": "mean_in_transformed_train_space",
                "logit": diagnostics.baseline_logit,
                "reference_version": diagnostics.reference_version,
                "reference_sha256": diagnostics.reference_sha256,
            },
            "factors": snapshot_view(result)["factors"],
            "consistency": {
                name: getattr(diagnostics, name)
                for name in (
                    "model_logit",
                    "contribution_sum",
                    "reconstructed_logit",
                    "reconstruction_error",
                )
            },
        },
        "limitations_warning": result.limitations_warning,
        "calculated_at": timestamp.isoformat().replace("+00:00", "Z"),
        "selected_what_if": None,
    }
    obj = ScoringAssessment(
        id=assessment_id,
        organization_id=org,
        application_id=application.id,
        application_version=version,
        features=features,
        feature_sha256=fingerprint(features),
        diagnostics=result.diagnostics.model_dump(mode="json"),
        response=response,
    )
    return persist(db, org, user, key, digest, obj, response, application, request.state.request_id)


def create_what_if(db, user, assessment_id, data, key, request):
    org = identity(db, user, write=True)
    assessment = assessment_for(db, assessment_id, org, user)
    changes = data.changes.model_dump(exclude_unset=True)
    digest = fingerprint(
        {"operation": "what-if", "assessment_id": str(assessment_id), "changes": changes}
    )
    previous = replay(db, org, user.id, key, digest)
    if previous is not None:
        return previous, True
    service = runtime(request)
    original_values = dict(assessment.features)
    alternative_values = {**original_values, **changes}
    if alternative_values == original_values:
        fail(422, "SCORING_NO_CHANGED_FIELDS")
    saved_model = assessment.response["model"]
    if (
        service.bundle_sha256 != saved_model["bundle_sha256"]
        or service.bundle.training_version != saved_model["model_version"]
        or service.reference_sha256
        != assessment.response["explanation"]["baseline"]["reference_sha256"]
    ):
        fail(409, "SCORING_MODEL_VERSION_UNAVAILABLE")
    application_id = assessment.application_id
    db.rollback()
    comparison = infer(
        lambda: compare_applications(
            service,
            CreditApplication.model_validate(original_values),
            CreditApplication.model_validate(alternative_values),
        )
    )
    what_if_id = new_id()
    response = {
        "what_if_id": what_if_id,
        "assessment_id": str(assessment_id),
        "schema_version": "1.0",
        "simulation_only": True,
        "changed_fields": comparison.changed_fields,
        "original": snapshot_view(comparison.original),
        "alternative": snapshot_view(comparison.alternative),
        "delta_percentage_points": comparison.delta_percentage_points,
        "limitations_warning": comparison.limitations_warning,
        "calculated_at": now().isoformat().replace("+00:00", "Z"),
    }
    application = application_for(db, application_id, user)
    obj = ScoringWhatIf(
        id=what_if_id,
        organization_id=org,
        assessment_id=str(assessment_id),
        features=alternative_values,
        diagnostics={
            "original": comparison.original.diagnostics.model_dump(mode="json"),
            "alternative": comparison.alternative.diagnostics.model_dump(mode="json"),
        },
        response=response,
    )
    return persist(db, org, user, key, digest, obj, response, application, request.state.request_id)
