from contextlib import asynccontextmanager
from datetime import timedelta
import hmac
import os
from pathlib import Path
import secrets
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models import Application, Base, LoginSession, Publication, User, now
from app.security import hash_password, token_hash, verify_password
from app.seed import seed_demo

STATIC = Path(__file__).parent / "static"
COOKIE = "club_session"
MAIN_CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
SWAGGER_JS = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"
SWAGGER_CSS = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginInput(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class ProfileInput(StrictModel):
    name: str = Field(min_length=2, max_length=80)
    headline: str = Field(default="", max_length=140)
    bio: str = Field(default="", max_length=2000)
    skills: str = Field(default="", max_length=300)


class PublicationInput(StrictModel):
    kind: Literal["startup", "vacancy"]
    title: str = Field(min_length=5, max_length=120)
    description: str = Field(min_length=20, max_length=5000)
    looking_for: str = Field(min_length=3, max_length=300)
    work_format: str = Field(default="По договорённости", min_length=2, max_length=80)


class PublicationStatus(StrictModel):
    status: Literal["open", "closed"]


class ApplicationInput(StrictModel):
    message: str = Field(min_length=10, max_length=2000)


class DecisionInput(StrictModel):
    status: Literal["accepted", "rejected"]


def public_user(u: User) -> dict:
    return {"id": u.id, "name": u.name, "headline": u.headline, "bio": u.bio, "skills": u.skills}


def publication_json(p: Publication, db: Session, current_user: User) -> dict:
    app = db.scalar(select(Application).where(Application.publication_id == p.id,
                                             Application.applicant_id == current_user.id))
    return {"id": p.id, "kind": p.kind, "title": p.title, "description": p.description,
            "looking_for": p.looking_for, "work_format": p.work_format, "status": p.status,
            "created_at": p.created_at.isoformat(), "author": public_user(db.get(User, p.author_id)),
            "is_mine": p.author_id == current_user.id,
            "my_application": {"id": app.id, "status": app.status} if app else None}


def application_json(a: Application, db: Session) -> dict:
    p = db.get(Publication, a.publication_id)
    return {"id": a.id, "message": a.message, "status": a.status,
            "created_at": a.created_at.isoformat(),
            "decided_at": a.decided_at.isoformat() if a.decided_at else None,
            "applicant": public_user(db.get(User, a.applicant_id)),
            "publication": {"id": p.id, "title": p.title, "kind": p.kind, "status": p.status,
                            "author": public_user(db.get(User, p.author_id))}}


def create_app(database_url: str | None = None, *, demo: bool | None = None, schema: str | None = None) -> FastAPI:
    url = database_url or os.getenv("DATABASE_URL", "postgresql+psycopg://club:local-demo-password@localhost:5432/club")
    engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=0,
                           connect_args={"options": f"-csearch_path={schema}"} if schema else {})
    session_factory = sessionmaker(engine, expire_on_commit=False)
    should_seed = demo if demo is not None else os.getenv("SEED_DEMO", "true").lower() == "true"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Base.metadata.create_all(engine)
        if should_seed:
            with session_factory() as db:
                seed_demo(db)
        yield
        engine.dispose()

    app = FastAPI(title="Свои люди — demo API", version="1.0.0", lifespan=lifespan, docs_url=None)
    app.state.engine = engine
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path != "/docs" or "Content-Security-Policy" not in response.headers:
            response.headers["Content-Security-Policy"] = MAIN_CSP
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/docs", include_in_schema=False)
    def swagger_docs():
        nonce = secrets.token_urlsafe(24)
        html = get_swagger_ui_html(openapi_url=app.openapi_url, title=f"{app.title} — API",
                                   swagger_js_url=SWAGGER_JS, swagger_css_url=SWAGGER_CSS,
                                   swagger_favicon_url="/static/favicon.svg")
        # Only the generated initializer gets an unpredictable nonce. No arbitrary
        # inline scripts are allowed, and the application UI keeps its strict CSP.
        body = html.body.decode().replace("<script>", f'<script nonce="{nonce}">')
        csp = (f"default-src 'self'; script-src 'self' {SWAGGER_JS} 'nonce-{nonce}'; "
               f"style-src 'self' {SWAGGER_CSS} 'unsafe-inline'; img-src 'self' data:; "
               "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        return HTMLResponse(body, headers={"Content-Security-Policy": csp, "Cache-Control": "no-store"})

    def get_db():
        with session_factory() as db:
            yield db

    def get_session(request: Request, db: Session = Depends(get_db)) -> LoginSession:
        raw = request.cookies.get(COOKIE, "")
        login = db.get(LoginSession, token_hash(raw)) if raw else None
        if not login or login.expires_at <= now():
            raise HTTPException(401, "Войдите в аккаунт, чтобы продолжить.")
        return login

    def get_user(login: LoginSession = Depends(get_session), db: Session = Depends(get_db)) -> User:
        user = db.get(User, login.user_id)
        if not user:
            raise HTTPException(401, "Аккаунт не найден.")
        return user

    def require_csrf(request: Request, login: LoginSession = Depends(get_session)):
        supplied = request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(supplied, login.csrf):
            raise HTTPException(403, "Обновите страницу и повторите действие.")

    @app.get("/health", include_in_schema=False)
    def health(db: Session = Depends(get_db)):
        db.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.post("/api/auth/login")
    def login(data: LoginInput, response: Response, request: Request, db: Session = Depends(get_db)):
        user = db.scalar(select(User).where(User.email == data.email.lower()))
        # The same hashing work is done for nonexistent users to reduce enumeration.
        valid = verify_password(data.password, user.password_hash) if user else verify_password(data.password, DUMMY_HASH)
        if not user or not valid:
            raise HTTPException(401, "Неверный email или пароль.")
        previous = request.cookies.get(COOKIE)
        if previous:
            old = db.get(LoginSession, token_hash(previous))
            if old:
                db.delete(old)
        raw = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        db.add(LoginSession(token_hash=token_hash(raw), user_id=user.id, csrf=csrf,
                            expires_at=now() + timedelta(hours=12)))
        db.commit()
        response.set_cookie(COOKIE, raw, max_age=43200, httponly=True, samesite="strict",
                            secure=os.getenv("COOKIE_SECURE", "false").lower() == "true", path="/")
        return {"user": {**public_user(user), "email": user.email}, "csrf_token": csrf}

    @app.post("/api/auth/logout", dependencies=[Depends(require_csrf)])
    def logout(response: Response, login: LoginSession = Depends(get_session), db: Session = Depends(get_db)):
        db.delete(login); db.commit()
        response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict")
        return {"ok": True}

    @app.get("/api/me")
    def me(user: User = Depends(get_user), login: LoginSession = Depends(get_session)):
        return {"user": {**public_user(user), "email": user.email}, "csrf_token": login.csrf}

    @app.patch("/api/me", dependencies=[Depends(require_csrf)])
    def update_profile(data: ProfileInput, user: User = Depends(get_user), db: Session = Depends(get_db)):
        for key, value in data.model_dump().items():
            setattr(user, key, value)
        db.commit()
        return {"user": {**public_user(user), "email": user.email}}

    @app.get("/api/publications")
    def publications(kind: Literal["startup", "vacancy"] | None = None,
                     q: str = Query(default="", max_length=100),
                     status: Literal["open", "closed", "all"] = "open", mine: bool = False,
                     limit: int = Query(default=20, ge=1, le=50), offset: int = Query(default=0, ge=0),
                     user: User = Depends(get_user), db: Session = Depends(get_db)):
        filters = []
        if kind: filters.append(Publication.kind == kind)
        if status != "all": filters.append(Publication.status == status)
        if mine: filters.append(Publication.author_id == user.id)
        if q.strip():
            term = q.strip().lower()
            filters.append(func.lower(Publication.title + " " + Publication.looking_for + " " + Publication.description).contains(term, autoescape=True))
        total = db.scalar(select(func.count()).select_from(Publication).where(*filters))
        rows = db.scalars(select(Publication).where(*filters).order_by(Publication.created_at.desc(), Publication.id.desc()).limit(limit).offset(offset)).all()
        return {"items": [publication_json(p, db, user) for p in rows], "total": total, "limit": limit, "offset": offset}

    @app.post("/api/publications", status_code=201, dependencies=[Depends(require_csrf)])
    def create_publication(data: PublicationInput, response: Response, user: User = Depends(get_user),
                           db: Session = Depends(get_db),
                           idempotency_key: str | None = Header(default=None, max_length=80)):
        key = idempotency_key or secrets.token_urlsafe(24)
        # Same user/key cannot create two rows, even for concurrent retries.
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        existing = db.scalar(select(Publication).where(Publication.author_id == user.id,
                                                       Publication.creation_key == key))
        if existing:
            if any(getattr(existing, k) != v for k, v in data.model_dump().items()):
                raise HTTPException(409, "Этот ключ запроса уже использован для другой публикации.")
            response.status_code = 200
            return publication_json(existing, db, user)
        row = Publication(author_id=user.id, creation_key=key, **data.model_dump())
        db.add(row); db.commit()
        return publication_json(row, db, user)

    @app.get("/api/publications/{publication_id}")
    def detail(publication_id: int, user: User = Depends(get_user), db: Session = Depends(get_db)):
        row = db.get(Publication, publication_id)
        if not row: raise HTTPException(404, "Публикация не найдена.")
        return publication_json(row, db, user)

    @app.patch("/api/publications/{publication_id}", dependencies=[Depends(require_csrf)])
    def publication_status(publication_id: int, data: PublicationStatus, user: User = Depends(get_user), db: Session = Depends(get_db)):
        row = db.scalar(select(Publication).where(Publication.id == publication_id).with_for_update())
        if not row: raise HTTPException(404, "Публикация не найдена.")
        if row.author_id != user.id: raise HTTPException(403, "Изменять публикацию может только автор.")
        row.status = data.status; db.commit()
        return publication_json(row, db, user)

    @app.post("/api/publications/{publication_id}/applications", dependencies=[Depends(require_csrf)])
    def apply(publication_id: int, data: ApplicationInput, response: Response,
              user: User = Depends(get_user), db: Session = Depends(get_db)):
        # Serialize submission and closing on this publication, not on the whole table.
        row = db.scalar(select(Publication).where(Publication.id == publication_id).with_for_update())
        if not row: raise HTTPException(404, "Публикация не найдена.")
        if row.author_id == user.id: raise HTTPException(409, "Нельзя откликнуться на свою публикацию.")
        existing = db.scalar(select(Application).where(Application.publication_id == row.id, Application.applicant_id == user.id))
        if existing:
            return application_json(existing, db)
        if row.status != "open": raise HTTPException(409, "Набор уже закрыт.")
        application = Application(publication_id=row.id, applicant_id=user.id, message=data.message)
        db.add(application); db.commit()
        response.status_code = 201
        return application_json(application, db)

    @app.get("/api/applications")
    def applications(direction: Literal["sent", "received"] = "sent",
                     user: User = Depends(get_user), db: Session = Depends(get_db)):
        statement = select(Application).join(Publication, Publication.id == Application.publication_id)
        statement = statement.where(Application.applicant_id == user.id) if direction == "sent" else statement.where(Publication.author_id == user.id)
        rows = db.scalars(statement.order_by(Application.created_at.desc(), Application.id.desc())).all()
        return {"items": [application_json(a, db) for a in rows]}

    @app.patch("/api/applications/{application_id}", dependencies=[Depends(require_csrf)])
    def decide(application_id: int, data: DecisionInput, user: User = Depends(get_user), db: Session = Depends(get_db)):
        row = db.scalar(select(Application).where(Application.id == application_id).with_for_update())
        if not row: raise HTTPException(404, "Отклик не найден.")
        publication = db.get(Publication, row.publication_id)
        if publication.author_id != user.id: raise HTTPException(403, "Решение может принять только автор публикации.")
        if row.status == data.status: return application_json(row, db)
        if row.status != "pending": raise HTTPException(409, "Решение уже принято и не может быть изменено.")
        row.status = data.status; row.decided_at = now(); db.commit()
        return application_json(row, db)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    return app


DUMMY_HASH = hash_password("not-a-real-account")
app = create_app()
