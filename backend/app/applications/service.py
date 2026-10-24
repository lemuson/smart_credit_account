import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import PurePath

from pydantic import ValidationError

from app.applications.checks import simulated_checks
from app.applications.dao import ApplicationDAO
from app.applications.decision import analyze
from app.applications.models import (
    Application,
    AuditEvent,
    CheckRun,
    Clarification,
    Document,
    Status,
)
from app.applications.schemas import ApplicationRead, Dossier, ValidationRead
from app.auth.models import Role
from app.auth.service import password_hash
from app.common import fail
from app.database import now
from app.loans.dao import LoanDAO
from app.loans.obligations import EXTERNAL_FIELDS, credit_obligations
from app.loans.service import LoanService
from app.products.schemas import ProductRead
from app.products.service import ProductService
from app.profiles.schemas import Company, Financials, ProfileUpdate
from app.profiles.service import ProfileService
from app.risk.service import RiskPolicyService

EDITABLE = {Status.DRAFT, Status.NEEDS_CLARIFICATION}
ALLOWED_TRANSITIONS = {
    Status.DRAFT: {Status.SUBMITTED},
    Status.SUBMITTED: {Status.PRIMARY_REVIEW},
    Status.PRIMARY_REVIEW: {Status.NEEDS_CLARIFICATION, Status.REJECTED, Status.AUTOMATIC_ANALYSIS},
    Status.NEEDS_CLARIFICATION: {Status.PRIMARY_REVIEW},
    Status.AUTOMATIC_ANALYSIS: {Status.OFFER_READY, Status.REJECTED},
    Status.OFFER_READY: {Status.OFFER_ACCEPTED, Status.OFFER_DECLINED},
    Status.OFFER_ACCEPTED: {Status.SIGNING},
    Status.SIGNING: {Status.DISBURSED},
}


class ApplicationService:
    def __init__(self, session):
        self.session = session
        self.dao = ApplicationDAO(session)

    def get(self, application_id, user):
        obj = self.dao.accessible(application_id, user)
        if not obj or (user.role == Role.MANAGER and obj.status == Status.DRAFT):
            fail(404, "APPLICATION_NOT_FOUND")
        return obj

    def version(self, obj, expected):
        if obj.version != expected:
            fail(409, "APPLICATION_VERSION_CONFLICT", current_version=obj.version)

    def state(self, obj, allowed):
        if obj.status not in allowed:
            fail(409, "INVALID_APPLICATION_STATE", status=obj.status)

    def assigned(self, obj, user):
        if obj.assigned_manager_id != user.id:
            fail(403, "APPLICATION_ASSIGNED_TO_ANOTHER_OFFICER")

    def audit(self, obj, user, action, previous=None, **details):
        self.session.add(
            AuditEvent(
                application_id=obj.id,
                actor_id=user.id if user else None,
                action=action,
                from_status=previous,
                to_status=obj.status,
                details=details,
            )
        )

    def transition(self, obj, target, user, action, **details):
        previous = obj.status
        if target not in ALLOWED_TRANSITIONS.get(previous, set()):
            fail(409, "INVALID_STATUS_TRANSITION")
        obj.status = target
        obj.updated_at = now()
        self.audit(obj, user, action, previous, **details)
        self.session.flush()

    def prefill(self, user, source_loan_id=None):
        profile = ProfileService(self.session).get(user.id)
        company, financials = dict(profile.company), dict(profile.financials)
        source_id = None
        if source_loan_id:
            source = LoanService(self.session).get(source_loan_id, user.id)
            # Свежий профиль имеет приоритет; история дополняет отсутствующие данные.
            company = {**source.company_snapshot, **company}
            financials = {**source.financials_snapshot, **financials}
            source_id = source.id
        else:
            loans = LoanDAO(self.session).list(user.id, limit=1)
            if loans:
                source_id = loans[0].id
                company = {**loans[0].company_snapshot, **company}
                financials = {**loans[0].financials_snapshot, **financials}
        # Поля анкеты относятся только к другим банкам; текущий банк считаем отдельно.
        for field in EXTERNAL_FIELDS:
            financials[field] = profile.financials.get(field, "0")
        return company, financials, source_id

    def create(self, data, user, draft_id=None):
        product = ProductService(self.session).get(data.product_id)
        if not product.active:
            fail(409, "PRODUCT_INACTIVE")
        company, financials, source_id = self.prefill(user, data.source_loan_id)
        obj = Application(
            **({"id": str(draft_id)} if draft_id else {}),
            client_id=user.id,
            product_id=product.id,
            purpose=data.purpose,
            amount=data.amount,
            term_months=data.term_months,
            source_loan_id=source_id,
            company=company,
            financials=financials,
            product_snapshot=ProductRead.model_validate(product).model_dump(mode="json"),
        )
        self.dao.add(obj)
        self.audit(obj, user, "DRAFT_CREATED", source_loan_id=source_id)
        self.session.flush()
        return obj

    def update(self, obj, data, user):
        self.version(obj, data.expected_version)
        self.state(obj, EDITABLE)
        if data.financials is not None:
            profile = ProfileService(self.session).get(user.id)
            for field in EXTERNAL_FIELDS:
                if getattr(data.financials, field) != Decimal(profile.financials.get(field) or "0"):
                    fail(422, "EXTERNAL_LIABILITIES_READ_ONLY")
        changed = []
        for field in data.model_fields_set - {"expected_version"}:
            value = getattr(data, field)
            if hasattr(value, "model_dump"):
                try:
                    if type(value).model_validate(getattr(obj, field)) == value:
                        continue
                except ValidationError:
                    pass
                value = value.model_dump(mode="json")
            if getattr(obj, field) != value:
                setattr(obj, field, value)
                changed.append(field)
        if changed:
            obj.data_revision += 1
            obj.updated_at = now()
            self.audit(
                obj,
                user,
                "APPLICATION_UPDATED",
                fields=sorted(changed),
                data_revision=obj.data_revision,
            )
        self.session.flush()
        return obj

    def save_draft(self, obj, data, user):
        self.state(obj, {Status.DRAFT})
        self.version(obj, data.expected_version)
        profile = ProfileService(self.session).get(user.id)
        company = data.company.model_dump(mode="json")
        financials = data.financials.model_dump(mode="json")
        financials.update({field: profile.financials.get(field, "0") for field in EXTERNAL_FIELDS})
        try:
            financials = Financials.model_validate(financials).model_dump(mode="json")
        except ValidationError:
            pass
        if obj.company != company or obj.financials != financials:
            obj.company, obj.financials = company, financials
            obj.data_revision += 1
            obj.updated_at = now()
            self.audit(obj, user, "APPLICATION_UPDATED", data_revision=obj.data_revision)
        self.session.flush()
        return obj

    def create_draft(self, data, user):
        existing = self.session.get(Application, str(data.draft_id))
        if existing:
            self.get(existing.id, user)
            self.state(existing, {Status.DRAFT})
            return existing
        obj = self.create(data, user, draft_id=data.draft_id)
        from app.applications.schemas import DraftUpdate

        return self.save_draft(
            obj,
            DraftUpdate(
                expected_version=obj.version,
                company=data.company,
                financials=data.financials,
            ),
            user,
        )

    def sync_profile(self, obj, data, user):
        self.version(obj, data.expected_version)
        self.state(obj, EDITABLE)
        profile_service = ProfileService(self.session)
        profile = profile_service.get(user.id)
        financials = {
            **obj.financials,
            **{field: profile.financials.get(field, "0") for field in EXTERNAL_FIELDS},
        }
        return profile_service.update(
            user.id, ProfileUpdate(company=obj.company, financials=financials)
        )

    def validate(self, obj):
        errors = []
        for field, model, payload in [
            ("company", Company, obj.company),
            ("financials", Financials, obj.financials),
        ]:
            try:
                model.model_validate(payload)
            except ValidationError as exc:
                errors.extend(
                    {"field": field + "." + ".".join(map(str, error["loc"])), "code": error["type"]}
                    for error in exc.errors()
                )
        p = obj.product_snapshot
        if obj.purpose not in p["purposes"]:
            errors.append({"field": "purpose", "code": "PURPOSE_NOT_SUPPORTED"})
        if not Decimal(p["min_amount"]) <= obj.amount <= Decimal(p["max_amount"]):
            errors.append({"field": "amount", "code": "AMOUNT_OUT_OF_RANGE"})
        if not p["min_term_months"] <= obj.term_months <= p["max_term_months"]:
            errors.append({"field": "term_months", "code": "TERM_OUT_OF_RANGE"})
        required = set(p["required_documents"])
        for clarification in self.dao.clarifications(obj.id):
            required.update(clarification.required_documents)
        uploaded = {d.kind for d in self.dao.documents(obj.id)}
        for kind in sorted(required - uploaded):
            errors.append({"field": f"documents.{kind}", "code": "REQUIRED_DOCUMENT_MISSING"})
        return ValidationRead(
            application_id=obj.id,
            product_id=obj.product_id,
            valid=not errors,
            errors=errors,
            data_revision=obj.data_revision,
        )

    def require_valid(self, obj):
        result = self.validate(obj)
        if not result.valid:
            fail(422, "APPLICATION_INVALID", errors=result.errors)

    def submit(self, obj, data, user):
        self.version(obj, data.expected_version)
        self.state(obj, {Status.DRAFT})
        if not data.confirmed:
            fail(422, "DATA_CONFIRMATION_REQUIRED")
        self.require_valid(obj)
        if not ProductService(self.session).get(obj.product_id).active:
            fail(409, "PRODUCT_INACTIVE")
        self.transition(obj, Status.SUBMITTED, user, "APPLICATION_SUBMITTED")
        return obj

    def take(self, obj, data, user):
        self.version(obj, data.expected_version)
        self.state(obj, {Status.SUBMITTED})
        obj.assigned_manager_id = user.id
        self.transition(obj, Status.PRIMARY_REVIEW, user, "ASSIGNED_TO_OFFICER")
        return obj

    def run_checks(self, obj, data, user):
        self.version(obj, data.expected_version)
        self.state(obj, {Status.PRIMARY_REVIEW})
        self.assigned(obj, user)
        self.require_valid(obj)
        run = self.dao.add(
            CheckRun(
                application_id=obj.id,
                data_revision=obj.data_revision,
                results=simulated_checks(obj, self.session),
            )
        )
        obj.updated_at = now()
        self.audit(
            obj, user, "EXTERNAL_CHECKS_COMPLETED", check_id=run.id, data_revision=obj.data_revision
        )
        self.session.flush()
        return run

    def request_clarification(self, obj, data, user):
        self.version(obj, data.expected_version)
        self.state(obj, {Status.PRIMARY_REVIEW})
        self.assigned(obj, user)
        item = Clarification(
            application_id=obj.id,
            manager_id=user.id,
            comment=data.comment,
            required_fields=data.required_fields,
            required_documents=[str(kind) for kind in data.required_documents],
        )
        self.dao.add(item)
        self.transition(
            obj,
            Status.NEEDS_CLARIFICATION,
            user,
            "CLARIFICATION_REQUESTED",
            clarification_id=item.id,
        )
        return obj

    def clarify(self, obj, data, user):
        self.version(obj, data.expected_version)
        self.state(obj, {Status.NEEDS_CLARIFICATION})
        if not data.confirmed:
            fail(422, "DATA_CONFIRMATION_REQUIRED")
        self.require_valid(obj)
        open_items = [item for item in self.dao.clarifications(obj.id) if item.responded_at is None]
        for item in open_items:
            item.response = data.response
            item.responded_at = now()
        # Даже текстовый ответ требует новой проверки источников.
        obj.data_revision += 1
        self.transition(obj, Status.PRIMARY_REVIEW, user, "CLARIFICATION_REPLIED")
        return obj

    def reject(self, obj, data, user):
        self.version(obj, data.expected_version)
        self.state(obj, {Status.PRIMARY_REVIEW})
        self.assigned(obj, user)
        obj.decision = {
            "outcome": "REJECT",
            "stage": "primary_review",
            "reasons": [data.comment],
            "demonstration_only": True,
        }
        self.transition(obj, Status.REJECTED, user, "PRIMARY_REVIEW_REJECTED")
        return obj

    def analyze(self, obj, data, user):
        self.version(obj, data.expected_version)
        self.state(obj, {Status.PRIMARY_REVIEW})
        self.assigned(obj, user)
        self.require_valid(obj)
        checks = self.dao.checks(obj.id)
        if not checks or checks[-1].data_revision != obj.data_revision:
            fail(409, "FRESH_EXTERNAL_CHECKS_REQUIRED")
        check = checks[-1]
        if check.results["discrepancies"]:
            fail(422, "UNRESOLVED_DISCREPANCIES", errors=check.results["discrepancies"])
        current = simulated_checks(obj, self.session)
        if current["bki"] != check.results["bki"]:
            fail(409, "LOAN_HISTORY_CHANGED_RERUN_CHECKS")
        self.audit(obj, user, "PRIMARY_REVIEW_PASSED", comment=data.comment, check_id=check.id)
        self.transition(obj, Status.AUTOMATIC_ANALYSIS, user, "AUTOMATIC_ANALYSIS_STARTED")
        policy = RiskPolicyService(self.session).get()
        obj.decision, obj.offer = analyze(
            obj,
            check.results,
            now().date(),
            policy.rules,
            f"demo-rules-1.0/revision-{policy.version}",
        )
        target = Status.OFFER_READY if obj.offer else Status.REJECTED
        self.transition(
            obj,
            target,
            None,
            "AUTOMATIC_DECISION",
            outcome=obj.decision["outcome"],
            reasons=obj.decision["reasons"],
            policy_version=obj.decision["policy_version"],
        )
        return obj

    def accept(self, obj, data, user):
        self.version(obj, data.expected_version)
        self.state(obj, {Status.OFFER_READY})
        self.transition(obj, Status.OFFER_ACCEPTED, user, "OFFER_ACCEPTED")
        contract = {
            "application_id": obj.id,
            "company": obj.company,
            "offer": obj.offer,
            "created_at": now().isoformat(),
            "demonstration_only": True,
            "text": (
                "Учебный проект кредитного договора. "
                "Подтверждение не является реальной выдачей средств."
            ),
        }
        digest = hashlib.sha256(
            json.dumps(contract, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        obj.contract = {**contract, "sha256": digest, "demo_signing_code": "123456"}
        obj.signing_code_hash = password_hash.hash("123456")
        obj.signing_expires_at = now() + timedelta(minutes=15)
        self.transition(obj, Status.SIGNING, None, "CONTRACT_GENERATED", contract_sha256=digest)
        return obj

    def decline(self, obj, data, user):
        self.version(obj, data.expected_version)
        self.state(obj, {Status.OFFER_READY})
        self.transition(obj, Status.OFFER_DECLINED, user, "OFFER_DECLINED")
        return obj

    def sign(self, obj, data, user):
        self.version(obj, data.expected_version)
        self.state(obj, {Status.SIGNING})
        if data.contract_sha256 != obj.contract["sha256"]:
            fail(409, "CONTRACT_HASH_MISMATCH")
        if obj.signing_expires_at < now():
            fail(409, "SIGNING_CODE_EXPIRED")
        if obj.signing_attempts >= 5:
            fail(429, "SIGNING_ATTEMPTS_EXCEEDED")
        if not password_hash.verify(data.code, obj.signing_code_hash):
            obj.signing_attempts += 1
            obj.updated_at = now()
            self.audit(obj, user, "SIGNING_CODE_REJECTED")
            # Счётчик должен пережить HTTP-ошибку; остальные операции в этой транзакции отсутствуют.
            self.session.commit()
            fail(422, "INVALID_SIGNING_CODE")
        offer = obj.offer
        LoanDAO(self.session).create(
            client_id=obj.client_id,
            application_id=obj.id,
            amount=Decimal(offer["amount"]),
            outstanding_balance=Decimal(offer["amount"]),
            monthly_payment=Decimal(offer["monthly_payment"]),
            term_months=offer["term_months"],
            annual_rate=Decimal(offer["annual_rate"]),
            company_snapshot=obj.company,
            financials_snapshot=obj.financials,
        )
        obj.signing_code_hash = None
        self.transition(
            obj,
            Status.DISBURSED,
            user,
            "DEMO_CONTRACT_SIGNED",
            contract_sha256=data.contract_sha256,
        )
        return obj

    def add_document(self, obj, user, kind, upload, expected_version, max_size):
        self.version(obj, expected_version)
        self.state(obj, EDITABLE)
        if len(self.dao.documents(obj.id)) >= 20:
            fail(422, "DOCUMENT_LIMIT_EXCEEDED")
        content = upload.file.read(max_size + 1)
        if len(content) > max_size:
            fail(413, "DOCUMENT_TOO_LARGE")
        signatures = {
            "application/pdf": b"%PDF-",
            "image/png": b"\x89PNG\r\n\x1a\n",
            "image/jpeg": b"\xff\xd8\xff",
        }
        signature = signatures.get(upload.content_type)
        if not signature or not content.startswith(signature):
            fail(422, "INVALID_DOCUMENT_FORMAT")
        filename = PurePath((upload.filename or "document").replace("\\", "/")).name
        if len(filename) > 255 or any(ord(char) < 32 for char in filename):
            fail(422, "INVALID_FILENAME")
        document = self.dao.add(
            Document(
                application_id=obj.id,
                kind=kind,
                filename=filename,
                content_type=upload.content_type,
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
                size=len(content),
            )
        )
        obj.data_revision += 1
        obj.updated_at = now()
        self.audit(obj, user, "DOCUMENT_UPLOADED", document_id=document.id, kind=str(kind))
        self.session.flush()
        return document

    def document(self, obj, document_id):
        for doc in self.dao.documents(obj.id):
            if doc.id == str(document_id):
                return doc
        fail(404, "DOCUMENT_NOT_FOUND")

    def delete_document(self, obj, document_id, expected_version, user):
        self.version(obj, expected_version)
        self.state(obj, EDITABLE)
        document = self.document(obj, document_id)
        self.session.delete(document)
        obj.data_revision += 1
        obj.updated_at = now()
        self.audit(obj, user, "DOCUMENT_DELETED", document_id=str(document_id))
        self.session.flush()

    def dossier(self, obj, user):
        hidden = {"APPLICATION_UPDATED", "DOCUMENT_UPLOADED", "DOCUMENT_DELETED"}
        if user.role == Role.CLIENT:
            hidden |= {
                "DRAFT_CREATED",
                "AUTOMATIC_DECISION",
                "EXTERNAL_CHECKS_COMPLETED",
                "PRIMARY_REVIEW_PASSED",
                "AUTOMATIC_ANALYSIS_STARTED",
                "SIGNING_CODE_REJECTED",
            }
        history = [event for event in self.dao.history(obj.id) if event.action not in hidden]
        return Dossier(
            **ApplicationRead.model_validate(obj).model_dump(),
            documents=self.dao.documents(obj.id),
            checks=self.dao.checks(obj.id) if user.role != Role.CLIENT else [],
            clarifications=self.dao.clarifications(obj.id),
            history=history,
            credit_obligations=credit_obligations(
                self.session,
                obj.client_id,
                ProfileService(self.session).get(obj.client_id).financials,
            ),
        )
