from uuid import UUID

from fastapi import APIRouter, Request

from app.auth.dao import UserDAO
from app.auth.dependencies import Admin, Client, CurrentUser
from app.auth.schemas import AdminUserCreate, Login, MeRead, Register, Token, UserActive, UserRead
from app.auth.service import AuthService
from app.common import DB, fail
from app.database import now
from app.profiles.dao import ProfileDAO
from app.profiles.schemas import Company, ProfileRead, ProfileUpdate
from app.profiles.service import ProfileService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=201)
def register(data: Register, db: DB):
    return AuthService(db).register(data)


@router.post("/login", response_model=Token)
def login(data: Login, request: Request, db: DB):
    return AuthService(db).login(data, request.app.state.settings)


@router.get("/me", response_model=MeRead)
def me(user: CurrentUser, db: DB):
    profile = ProfileDAO(db).for_user(user.id)
    return MeRead(
        **UserRead.model_validate(user).model_dump(),
        companies=[profile.company] if profile and profile.company else [],
    )


admin_router = APIRouter(prefix="/admin/users", tags=["admin"])


@admin_router.post("", response_model=UserRead, status_code=201)
def create_user(data: AdminUserCreate, db: DB, user: Admin):
    return AuthService(db).register(data, data.role)


@admin_router.patch("/{user_id}", response_model=UserRead)
def activate_user(user_id: UUID, data: UserActive, db: DB, user: Admin):
    if str(user_id) == user.id:
        fail(409, "CANNOT_DEACTIVATE_SELF")
    target = UserDAO(db).get(str(user_id))
    if not target:
        fail(404, "USER_NOT_FOUND")
    target.active = data.active
    db.flush()
    return target


@router.post("/company", response_model=ProfileRead)
def save_company(data: ProfileUpdate, db: DB, user: Client):
    return ProfileService(db).update(user.id, data)


@router.get("/company/suggest/{inn}", response_model=Company)
def suggest_company(inn: str, user: Client):
    from pydantic import ValidationError

    try:
        return Company(
            name=f"Демо-компания {inn}",
            inn=inn,
            registration_date=now().date().replace(year=now().year - 5, day=1),
            address="Демонстрационный адрес, требуется подтверждение",
            industry="62.01",
        )
    except ValidationError:
        fail(422, "INVALID_INN")
