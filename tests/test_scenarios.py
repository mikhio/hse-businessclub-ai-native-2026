from concurrent.futures import ThreadPoolExecutor
import re

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import Application, LoginSession, Publication
from app.security import hash_password, verify_password


def publish(client, **updates):
    data = {"kind": "startup", "title": "Новый учебный проект", "description": "Делаем полезный сервис и ищем команду для первой версии.",
            "looking_for": "Backend-разработчик", "work_format": "Удалённо"}
    data.update(updates)
    response = client.post("/api/publications", json=data)
    assert response.status_code == 201, response.text
    return response.json()


def send(client, publication_id):
    return client.post(f"/api/publications/{publication_id}/applications", json={"message": "Хочу помочь с backend и обсудить первый прототип."})


def test_complete_two_user_scenario(clients):
    owner, applicant, _ = clients
    publication = publish(owner)
    assert any(p["id"] == publication["id"] for p in applicant.get("/api/publications").json()["items"])
    application = send(applicant, publication["id"])
    assert application.status_code == 201
    aid = application.json()["id"]
    incoming = owner.get("/api/applications?direction=received").json()["items"]
    assert any(a["id"] == aid and a["status"] == "pending" for a in incoming)
    decision = owner.patch(f"/api/applications/{aid}", json={"status": "accepted"})
    assert decision.status_code == 200
    assert decision.json()["decided_at"] is not None
    outgoing = applicant.get("/api/applications?direction=sent").json()["items"]
    assert next(a for a in outgoing if a["id"] == aid)["status"] == "accepted"


def test_outsider_cannot_edit_or_decide_or_list_private_applications(clients):
    owner, applicant, outsider = clients
    publication = publish(owner)
    aid = send(applicant, publication["id"]).json()["id"]
    assert outsider.patch(f"/api/publications/{publication['id']}", json={"status": "closed"}).status_code == 403
    assert outsider.patch(f"/api/applications/{aid}", json={"status": "accepted"}).status_code == 403
    assert applicant.patch(f"/api/applications/{aid}", json={"status": "accepted"}).status_code == 403
    for direction in ("sent", "received"):
        assert all(a["id"] != aid for a in outsider.get(f"/api/applications?direction={direction}").json()["items"])
    assert "my_application" in outsider.get(f"/api/publications/{publication['id']}").json()
    assert outsider.get(f"/api/publications/{publication['id']}").json()["my_application"] is None


def test_repeat_application_and_decision_are_idempotent(clients, app):
    owner, applicant, _ = clients
    p = publish(owner)
    first, second = send(applicant, p["id"]), send(applicant, p["id"])
    assert (first.status_code, second.status_code) == (201, 200)
    aid = first.json()["id"]
    assert second.json()["id"] == aid
    for _ in range(2):
        assert owner.patch(f"/api/applications/{aid}", json={"status": "rejected"}).status_code == 200
    assert owner.patch(f"/api/applications/{aid}", json={"status": "accepted"}).status_code == 409
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Application).where(Application.publication_id == p["id"])) == 1


def test_closed_publication_and_self_application(clients):
    owner, applicant, outsider = clients
    p = publish(owner)
    assert send(owner, p["id"]).status_code == 409
    first = send(applicant, p["id"]).json()
    assert owner.patch(f"/api/publications/{p['id']}", json={"status": "closed"}).status_code == 200
    assert send(outsider, p["id"]).status_code == 409
    assert send(applicant, p["id"]).json()["id"] == first["id"]
    assert all(row["id"] != p["id"] for row in outsider.get("/api/publications").json()["items"])
    assert owner.patch(f"/api/applications/{first['id']}", json={"status": "accepted"}).status_code == 200
    assert owner.patch(f"/api/publications/{p['id']}", json={"status": "open"}).status_code == 200
    assert send(outsider, p["id"]).status_code == 201


def test_one_person_can_publish_and_apply(clients):
    owner, applicant, _ = clients
    p = publish(owner)
    own = publish(applicant, kind="vacancy")
    assert send(applicant, p["id"]).status_code == 201
    assert send(owner, own["id"]).status_code == 201
    assert applicant.get("/api/publications?mine=true").json()["total"] >= 1
    assert applicant.get("/api/applications?direction=sent").json()["items"]
    assert applicant.get("/api/applications?direction=received").json()["items"]


def test_authentication_and_csrf(app, clients):
    anonymous = TestClient(app)
    assert anonymous.get("/api/publications").status_code == 401
    assert anonymous.get("/api/applications").status_code == 401
    assert anonymous.get("/api/me").status_code == 401
    assert anonymous.post("/api/auth/login", json={"email": "missing@example.test", "password": "wrong"}).status_code == 401
    owner, _, _ = clients
    old_csrf = owner.headers.pop("X-CSRF-Token")
    assert owner.patch("/api/me", json={"name": "Изменено"}).status_code == 403
    owner.headers["X-CSRF-Token"] = old_csrf
    assert owner.post("/api/auth/logout").status_code == 200
    assert owner.get("/api/me").status_code == 401


def test_session_tokens_are_hashed_and_cookie_is_httponly(app):
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"email": "anna@example.test", "password": "ClubDemo2026!"})
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    raw = client.cookies["club_session"]
    with app.state.session_factory() as db:
        sessions = db.scalars(select(LoginSession)).all()
        assert all(row.token_hash != raw for row in sessions)


def test_profile_survives_new_session_without_leaking_email(clients, app):
    owner, applicant, _ = clients
    updated = {"name": "Анна Новая", "headline": "Демо-основательница", "bio": "Описание профиля", "skills": "Продукт, аналитика"}
    assert owner.patch("/api/me", json=updated).status_code == 200
    fresh = TestClient(app)
    fresh.post("/api/auth/login", json={"email": "anna@example.test", "password": "ClubDemo2026!"})
    assert fresh.get("/api/me").json()["user"]["name"] == updated["name"]
    rows = applicant.get("/api/publications").json()["items"]
    assert all("email" not in p["author"] and "password_hash" not in p["author"] for p in rows)


def test_filters_pagination_literal_search_and_empty_result(clients):
    owner, _, _ = clients
    p = publish(owner, title="Стартап 100% полезный")
    assert all(row["kind"] == "vacancy" for row in owner.get("/api/publications?kind=vacancy").json()["items"])
    first = owner.get("/api/publications?limit=2&offset=0").json()
    second = owner.get("/api/publications?limit=2&offset=2").json()
    assert len(first["items"]) == 2
    assert not ({p["id"] for p in first["items"]} & {p["id"] for p in second["items"]})
    result = owner.get("/api/publications", params={"q": "100%"}).json()
    assert [row["id"] for row in result["items"]] == [p["id"]]
    assert owner.get("/api/publications?q=definitely-not-found").json()["total"] == 0


def test_validation_and_missing_resources(clients):
    owner, applicant, _ = clients
    assert owner.post("/api/publications", json={"kind": "fake"}).status_code == 422
    assert owner.patch("/api/me", json={"name": "  "}).status_code == 422
    assert owner.get("/api/publications/999999").status_code == 404
    assert owner.patch("/api/applications/999999", json={"status": "accepted"}).status_code == 404
    p = publish(owner)
    assert applicant.post(f"/api/publications/{p['id']}/applications", json={"message": "short"}).status_code == 422
    assert owner.get("/api/publications?limit=999999").status_code == 422


def test_publication_idempotency_key(clients):
    owner, _, _ = clients
    data = {"kind": "startup", "title": "Без повторных публикаций", "description": "Один сетевой запрос повторяется безопасно и не создаёт дубль.", "looking_for": "Команда"}
    first = owner.post("/api/publications", json=data, headers={"Idempotency-Key": "request-one"})
    second = owner.post("/api/publications", json=data, headers={"Idempotency-Key": "request-one"})
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    data["title"] = "Другое содержание"
    assert owner.post("/api/publications", json=data, headers={"Idempotency-Key": "request-one"}).status_code == 409


def test_concurrent_duplicate_application_is_single_row(clients, app):
    owner, applicant, _ = clients
    p = publish(owner)
    copies = []
    for _ in range(2):
        client = TestClient(app)
        result = client.post("/api/auth/login", json={"email": "max@example.test", "password": "ClubDemo2026!"})
        client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
        copies.append(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda c: send(c, p["id"]), copies))
    assert sorted(r.status_code for r in results) == [200, 201]
    assert len({r.json()["id"] for r in results}) == 1
    for client in copies: client.close()


def test_concurrent_conflicting_decisions_do_not_overwrite(clients, app):
    owner, applicant, _ = clients
    p = publish(owner)
    aid = send(applicant, p["id"]).json()["id"]
    copies = []
    for _ in range(2):
        client = TestClient(app)
        result = client.post("/api/auth/login", json={"email": "anna@example.test", "password": "ClubDemo2026!"})
        client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
        copies.append(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda item: item[0].patch(f"/api/applications/{aid}", json={"status": item[1]}), zip(copies, ("accepted", "rejected"))))
    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r.json()["status"] for r in results if r.status_code == 200)
    actual = next(a for a in applicant.get("/api/applications?direction=sent").json()["items"] if a["id"] == aid)
    assert actual["status"] == winner
    for client in copies: client.close()


def test_password_hashing_uses_independent_salt():
    first, second = hash_password("password"), hash_password("password")
    assert first != second
    assert verify_password("password", first)
    assert not verify_password("wrong", first)


def test_index_and_security_headers(app):
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert 'lang="ru"' in response.text
    assert response.headers["x-frame-options"] == "DENY"
    assert "script-src 'self'" in response.headers["content-security-policy"]


def test_docs_nonce_is_unique_and_policy_is_limited_to_docs(app):
    client = TestClient(app)
    first, second = client.get("/docs"), client.get("/docs")
    assert first.status_code == second.status_code == 200
    nonces = [re.search(r'<script nonce="([^"]+)">', response.text).group(1) for response in (first, second)]
    assert nonces[0] != nonces[1]
    assert f"'nonce-{nonces[0]}'" in first.headers["content-security-policy"]
    assert "cdn.jsdelivr.net" in first.headers["content-security-policy"]
    assert "'unsafe-inline'" not in first.headers["content-security-policy"].split("style-src")[0]
    for path in ("/", "/api/me", "/openapi.json"):
        policy = client.get(path).headers["content-security-policy"]
        assert "cdn.jsdelivr.net" not in policy
        assert "'unsafe-inline'" not in policy
        assert "nonce-" not in policy
