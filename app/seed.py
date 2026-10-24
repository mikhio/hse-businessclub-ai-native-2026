"""Idempotent fictional fixtures; deliberately separate from application logic."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, Publication, User
from app.security import hash_password

DEMO_PASSWORD = "ClubDemo2026!"


def seed_demo(db: Session) -> None:
    if db.scalar(select(User.id).where(User.email == "anna@example.test")):
        return
    anna = User(email="anna@example.test", name="Анна Соколова", headline="Основательница / продукт",
                bio="Собираю команду для вымышленного проекта StudyPal. Люблю превращать исследование в работающий продукт.",
                skills="Product, UX, исследование", password_hash=hash_password(DEMO_PASSWORD))
    max_ = User(email="max@example.test", name="Максим Орлов", headline="Backend-разработчик",
                bio="Вымышленный участник: Python, PostgreSQL и интерес к образовательным продуктам.",
                skills="Python, PostgreSQL, FastAPI", password_hash=hash_password(DEMO_PASSWORD))
    maria = User(email="maria@example.test", name="Мария Белова", headline="Дизайнер / бренд",
                 bio="Вымышленная участница. Исследую, рисую интерфейсы и ищу небольшой проект для портфолио.",
                 skills="Figma, UI/UX, branding", password_hash=hash_password(DEMO_PASSWORD))
    db.add_all([anna, max_, maria]); db.flush()
    rows = [
        Publication(author_id=anna.id, kind="startup", title="StudyPal — учиться вместе проще",
                    description="Демо-проект: сервис, который помогает студентам находить партнёров для подготовки к экзаменам. Уже есть прототип и интервью. Хочу проверить продукт вместе с командой и запустить первый пилот.",
                    looking_for="Python-разработчик и UX-дизайнер", work_format="Москва / удалённо"),
        Publication(author_id=anna.id, kind="vacancy", title="Дизайнер в команду студенческого фестиваля",
                    description="Вымышленная вакансия: нужна понятная айдентика и несколько экранов регистрации. Небольшая команда, конкретный объём, возможность показать результат в портфолио. Условия обсудим до старта.",
                    looking_for="Figma, аккуратная типографика, интерес к событиям", work_format="Гибрид"),
        Publication(author_id=max_.id, kind="startup", title="Local Cup — кофе рядом с кампусом",
                    description="Демо-идея: предзаказ кофе в кофейнях около университета. Ищу человека, который поможет провести интервью с владельцами и проверить первую бизнес-гипотезу.",
                    looking_for="Исследователь / business development", work_format="Москва"),
        Publication(author_id=maria.id, kind="vacancy", title="Frontend-разработчик для портфолио-платформы",
                    description="Вымышленный проект для демонстрации: хочу собрать небольшую платформу студенческих портфолио. Макеты готовы, нужен напарник для первой версии и совместного тестирования.",
                    looking_for="HTML, CSS, JavaScript", work_format="Удалённо"),
    ]
    db.add_all(rows); db.flush()
    db.add(Application(publication_id=rows[0].id, applicant_id=max_.id,
                       message="Привет! Хочу помочь с backend. Могу обсудить API и первый сценарий на этой неделе."))
    db.commit()
