from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from app.applications.contract_pdf import contract_pdf
from app.applications.models import Status
from app.applications.schemas import (
    ApplicationCreate,
    ApplicationRead,
    ApplicationUpdate,
    CheckRead,
    ClarificationCreate,
    ClarificationRead,
    ClarificationReply,
    DocumentRead,
    Dossier,
    ReviewAction,
    Sign,
    Submit,
    ValidationRead,
    VersionAction,
)
from app.applications.service import ApplicationService
from app.auth.dependencies import Client, CurrentUser, Manager, require_client, require_manager
from app.common import DB, fail
from app.products.schemas import DocumentKind

client_router = APIRouter(
    prefix="/client/applications",
    tags=["client-applications"],
    dependencies=[Depends(require_client)],
)
bank_router = APIRouter(
    prefix="/bank/applications", tags=["bank-applications"], dependencies=[Depends(require_manager)]
)
compat_router = APIRouter(prefix="/applications", tags=["application-tools"])


@client_router.post("", response_model=ApplicationRead, status_code=201)
def create(data: ApplicationCreate, db: DB, user: Client):
    return ApplicationService(db).create(data, user)


@client_router.get("", response_model=list[ApplicationRead])
def list_client(
    db: DB,
    user: Client,
    status: Status | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    return ApplicationService(db).dao.list(user, status, offset, limit)


@client_router.get("/{application_id}", response_model=Dossier)
@bank_router.get("/{application_id}/dossier", response_model=Dossier)
def detail(application_id: UUID, db: DB, user: CurrentUser):
    service = ApplicationService(db)
    return service.dossier(service.get(application_id, user), user)


@client_router.put("/{application_id}", response_model=ApplicationRead)
def update(application_id: UUID, data: ApplicationUpdate, db: DB, user: Client):
    service = ApplicationService(db)
    return service.update(service.get(application_id, user), data, user)


@client_router.post("/{application_id}/submit", response_model=ApplicationRead)
def submit(application_id: UUID, data: Submit, db: DB, user: Client):
    service = ApplicationService(db)
    return service.submit(service.get(application_id, user), data, user)


@client_router.post("/{application_id}/documents", response_model=DocumentRead, status_code=201)
def upload_document(
    application_id: UUID,
    request: Request,
    db: DB,
    user: Client,
    kind: DocumentKind = Form(),
    expected_version: int = Form(ge=1),
    file: UploadFile = File(),
):
    service = ApplicationService(db)
    return service.add_document(
        service.get(application_id, user),
        user,
        kind,
        file,
        expected_version,
        request.app.state.settings.max_document_bytes,
    )


@client_router.get("/{application_id}/documents/{document_id}")
@bank_router.get("/{application_id}/documents/{document_id}")
def download_document(application_id: UUID, document_id: UUID, db: DB, user: CurrentUser):
    service = ApplicationService(db)
    doc = service.document(service.get(application_id, user), document_id)
    return Response(
        doc.content,
        media_type=doc.content_type,
        headers={"Content-Disposition": "attachment", "X-Content-Type-Options": "nosniff"},
    )


@client_router.delete("/{application_id}/documents/{document_id}", status_code=204)
def delete_document(
    application_id: UUID,
    document_id: UUID,
    db: DB,
    user: Client,
    expected_version: int = Query(ge=1),
):
    service = ApplicationService(db)
    service.delete_document(service.get(application_id, user), document_id, expected_version, user)
    return Response(status_code=204)


@client_router.get("/{application_id}/clarification", response_model=list[ClarificationRead])
def clarifications(application_id: UUID, db: DB, user: Client):
    service = ApplicationService(db)
    return service.dao.clarifications(service.get(application_id, user).id)


@client_router.post("/{application_id}/clarify", response_model=ApplicationRead)
def clarify(application_id: UUID, data: ClarificationReply, db: DB, user: Client):
    service = ApplicationService(db)
    return service.clarify(service.get(application_id, user), data, user)


@client_router.get("/{application_id}/offer")
def offer(application_id: UUID, db: DB, user: Client):
    obj = ApplicationService(db).get(application_id, user)
    if not obj.offer:
        fail(409, "OFFER_NOT_READY")
    return obj.offer


@client_router.post("/{application_id}/offer/accept", response_model=ApplicationRead)
def accept(application_id: UUID, data: VersionAction, db: DB, user: Client):
    service = ApplicationService(db)
    return service.accept(service.get(application_id, user), data, user)


@client_router.post("/{application_id}/offer/decline", response_model=ApplicationRead)
def decline(application_id: UUID, data: VersionAction, db: DB, user: Client):
    service = ApplicationService(db)
    return service.decline(service.get(application_id, user), data, user)


@client_router.get("/{application_id}/contract")
def contract(application_id: UUID, db: DB, user: Client):
    obj = ApplicationService(db).get(application_id, user)
    if not obj.contract:
        fail(409, "CONTRACT_NOT_READY")
    return obj.contract


@client_router.get("/{application_id}/contract/pdf")
@bank_router.get("/{application_id}/contract/pdf")
def download_contract(application_id: UUID, db: DB, user: CurrentUser):
    obj = ApplicationService(db).get(application_id, user)
    if not obj.contract:
        fail(409, "CONTRACT_NOT_READY")
    return Response(
        contract_pdf(obj.contract),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="contract-{obj.id}.pdf"'},
    )


@client_router.post("/{application_id}/sign", response_model=ApplicationRead)
def sign(application_id: UUID, data: Sign, db: DB, user: Client):
    service = ApplicationService(db)
    return service.sign(service.get(application_id, user), data, user)


@bank_router.get("/queue", response_model=list[ApplicationRead])
def queue(
    db: DB,
    user: Manager,
    status: Status | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    return ApplicationService(db).dao.list(user, status, offset, limit)


@bank_router.post("/{application_id}/take-to-work", response_model=ApplicationRead)
def take(application_id: UUID, data: VersionAction, db: DB, user: Manager):
    service = ApplicationService(db)
    return service.take(service.get(application_id, user), data, user)


@bank_router.post("/{application_id}/run-external-checks", response_model=CheckRead)
def checks(application_id: UUID, data: VersionAction, db: DB, user: Manager):
    service = ApplicationService(db)
    return service.run_checks(service.get(application_id, user), data, user)


@bank_router.post("/{application_id}/request-clarification", response_model=ApplicationRead)
def request_clarification(application_id: UUID, data: ClarificationCreate, db: DB, user: Manager):
    service = ApplicationService(db)
    return service.request_clarification(service.get(application_id, user), data, user)


@bank_router.post("/{application_id}/reject-primary", response_model=ApplicationRead)
def reject(application_id: UUID, data: ReviewAction, db: DB, user: Manager):
    service = ApplicationService(db)
    return service.reject(service.get(application_id, user), data, user)


@bank_router.post("/{application_id}/pass-to-auto-analysis", response_model=ApplicationRead)
def analyze(application_id: UUID, data: ReviewAction, db: DB, user: Manager):
    service = ApplicationService(db)
    return service.analyze(service.get(application_id, user), data, user)


@compat_router.get("/{application_id}/status")
def status(application_id: UUID, db: DB, user: CurrentUser):
    obj = ApplicationService(db).get(application_id, user)
    return {
        "application_id": obj.id,
        "product_id": obj.product_id,
        "status": obj.status,
        "version": obj.version,
        "updated_at": obj.updated_at,
    }


@compat_router.post("/{application_id}/validate", response_model=ValidationRead)
def validate(application_id: UUID, db: DB, user: CurrentUser):
    service = ApplicationService(db)
    return service.validate(service.get(application_id, user))
