import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from app.auth.models import Role
from app.auth.schemas import Register
from app.auth.service import AuthService
from app.database import make_engine
from examples.test_database import temporary_database

with temporary_database() as url:
    os.environ["DATABASE_URL"] = url
    os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)
    command.upgrade(Config("alembic.ini"), "head")
    engine = make_engine(url)
    with Session(engine) as session, session.begin():
        AuthService(session).register(
            Register(email="officer@example.com", password="demo-password-123"), Role.MANAGER
        )
    engine.dispose()
    subprocess.run(
        [sys.executable, "-m", "app.cli", "seed-products"], check=True, capture_output=True
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as api:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError(server.communicate()[1].decode())
                try:
                    response = api.get("/health")
                    if response.status_code == 200:
                        break
                except httpx.ConnectError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("HTTP server did not become ready")

            def call(method, path, headers=None, **kwargs):
                response = api.request(method, "/api/v1" + path, headers=headers, **kwargs)
                if response.status_code not in (200, 201):
                    raise AssertionError((path, response.status_code, response.text))
                return response.json()

            call(
                "POST",
                "/auth/register",
                json={"email": "client@example.com", "password": "demo-password-123"},
            )
            client_token = call(
                "POST",
                "/auth/login",
                json={"email": "client@example.com", "password": "demo-password-123"},
            )["access_token"]
            officer_token = call(
                "POST",
                "/auth/login",
                json={"email": "officer@example.com", "password": "demo-password-123"},
            )["access_token"]
            client = {"Authorization": "Bearer " + client_token}
            officer = {"Authorization": "Bearer " + officer_token}
            call(
                "POST",
                "/auth/company",
                client,
                json={
                    "company": {
                        "name": "Demo",
                        "inn": "7700000009",
                        "registration_date": "2020-01-01",
                        "address": "Demo street",
                        "industry": "62.01",
                    },
                    "financials": {
                        "annual_revenue": "24000000",
                        "monthly_expenses": "500000",
                        "monthly_debt_payments": "0",
                        "outstanding_debt": "0",
                        "credit_history": "good",
                        "overdue_days": 0,
                        "has_collateral": False,
                    },
                },
            )
            product = call("GET", "/catalog/products", client)[0]
            app = call(
                "POST",
                "/client/applications",
                client,
                json={
                    "product_id": product["id"],
                    "purpose": "working_capital",
                    "amount": "1000000",
                    "term_months": 24,
                },
            )
            base = "/client/applications/" + app["id"]
            bank = "/bank/applications/" + app["id"]
            for kind in product["required_documents"]:
                call(
                    "POST",
                    base + "/documents",
                    client,
                    data={"kind": kind, "expected_version": app["version"]},
                    files={
                        "file": (
                            "demo.pdf",
                            Path("examples/demo.pdf").read_bytes(),
                            "application/pdf",
                        )
                    },
                )
                app = call("GET", base, client)
            app = call(
                "POST",
                base + "/submit",
                client,
                json={"expected_version": app["version"], "confirmed": True},
            )
            assert len(call("GET", "/bank/applications/queue", officer)) == 1
            app = call(
                "POST", bank + "/take-to-work", officer, json={"expected_version": app["version"]}
            )
            call(
                "POST",
                bank + "/run-external-checks",
                officer,
                json={"expected_version": app["version"]},
            )
            app = call("GET", bank + "/dossier", officer)
            app = call(
                "POST",
                bank + "/pass-to-auto-analysis",
                officer,
                json={"expected_version": app["version"], "comment": "Verified"},
            )
            assert app["status"] == "OFFER_READY"
            app = call(
                "POST", base + "/offer/accept", client, json={"expected_version": app["version"]}
            )
            app = call(
                "POST",
                base + "/sign",
                client,
                json={
                    "expected_version": app["version"],
                    "code": "123456",
                    "contract_sha256": app["contract"]["sha256"],
                },
            )
            assert app["status"] == "DISBURSED"
            assert len(call("GET", "/client/loans", client)) == 1
            assert any(
                item["id"] == "issued" for item in call("GET", "/client/feed", client)["items"]
            )
            print(
                "LIVE HTTP SMOKE PASSED: registration -> review -> scoring -> signing -> "
                "DISBURSED, history and feed"
            )
    finally:
        server.terminate()
        server.communicate(timeout=5)
