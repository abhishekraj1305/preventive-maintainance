"""Real browser acceptance check against an isolated disposable Django test DB.

Runs desktop and mobile, including forced password changes, PM rejection and
approval, breakdown restoration, shared updates, offline indication and XLSX.
Screenshots are written to git-ignored artifacts/browser/.
"""

import os
import re
import sys
import secrets
import subprocess
import time
from pathlib import Path
from datetime import timedelta
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ["DEBUG"] = "1"
os.environ["DEMO_MODE"] = "1"
os.environ["SECURE_SSL_REDIRECT"] = "0"

import django

django.setup()
from django.conf import settings
from django.core.management import call_command
from django.db import connection, connections
from django.test.utils import setup_databases, teardown_databases
from django.utils import timezone
from maintenance.models import User, Machine, PMOccurrence
from playwright.sync_api import sync_playwright, expect


def main():
    output = ROOT / "artifacts/browser"
    output.mkdir(parents=True, exist_ok=True)
    password = "Demo-" + secrets.token_urlsafe(18)
    new_password = "Changed-" + secrets.token_urlsafe(18)
    os.environ["DEMO_PASSWORD"] = password
    settings.DEMO_MODE = True
    original = setup_databases(verbosity=0, interactive=False)
    server = None
    try:
        call_command("seed_demo", verbosity=0)
        User.objects.create_superuser("browser.admin", password=password, must_change_password=True)
        database = connection.settings_dict
        if connection.vendor != "postgresql":
            raise RuntimeError("Browser acceptance checks require a PostgreSQL test database.")
        from urllib.parse import quote

        env = os.environ.copy()
        env["DATABASE_URL"] = (
            f"postgresql://{quote(database['USER'], safe='')}:{quote(database['PASSWORD'], safe='')}@{database['HOST']}:{database['PORT']}/{database['NAME']}"
        )
        env["SECRET_KEY"] = settings.SECRET_KEY
        call_command("collectstatic", verbosity=0, interactive=False)
        log = (output / "server.log").open("w", encoding="utf-8")
        server = subprocess.Popen(
            [sys.executable, "manage.py", "runserver", "127.0.0.1:8012", "--noreload"],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        url = "http://127.0.0.1:8012"
        for _ in range(60):
            try:
                if urlopen(url + "/health/", timeout=2).status == 200:
                    break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("Browser test server did not start; inspect artifacts/browser/server.log")
        machine_id = Machine.objects.get(plant__code="DEMO-NORTH", code="PP-103").pk
        task_id = PMOccurrence.objects.filter(technician__username="north.tech", status="pending").first().pk
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            errors = []

            def session(username, mobile=False):
                ctx = browser.new_context(
                    viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 1050},
                    is_mobile=mobile,
                    has_touch=mobile,
                )
                # A wrong device clock must not affect the server-based countdowns.
                ctx.add_init_script("Date.now = () => 4102444800000;")
                page = ctx.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(url + "/login/")
                page.get_by_label("User ID").fill(username)
                page.locator('input[name="password"]').fill(password)
                page.get_by_role("button", name="Sign in").click()
                page.wait_for_url("**/password/")
                page.get_by_label("Old password").fill(password)
                page.locator('input[name="new_password1"]').fill(new_password)
                page.get_by_label("New password confirmation").fill(new_password)
                page.get_by_role("button", name="Save password").click()
                page.wait_for_url(url + "/")
                return ctx, page

            admin_ctx, admin_page = session("browser.admin")
            admin_page.screenshot(path=str(output / "dashboard-desktop.png"), full_page=True)
            for path in [
                "/machines/",
                "/pm/",
                "/approvals/",
                "/breakdowns/",
                "/runtime/",
                "/notifications/",
                "/reports/",
                "/settings/",
                "/import/",
            ]:
                response = admin_page.goto(url + path)
                assert response.status == 200, (path, response.status)
                expect(admin_page.locator("h1")).to_be_visible()
            admin_page.goto(url + "/reports/")
            with admin_page.expect_download() as download_info:
                admin_page.get_by_role("link", name="Download Excel").click()
            download_info.value.save_as(str(output / "report.xlsx"))
            operator_ctx, operator = session("north.operator", mobile=True)
            operator.screenshot(path=str(output / "dashboard-mobile.png"), full_page=True)
            assert operator.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile horizontal overflow"
            operator.get_by_role("button", name="Toggle navigation").click()
            expect(operator.locator("#sidebar")).to_have_class("sidebar open")
            operator.locator("#sidebar-shade").click(position={"x": 350, "y": 50})
            operator.goto(url + "/breakdowns/new/")
            operator.locator('select[name="machine"]').select_option(str(machine_id))
            occurred = timezone.localtime(timezone.now() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
            operator.get_by_label("Breakdown occurred").fill(occurred)
            operator.get_by_label("Description").fill("Browser acceptance: stopped during cycle")
            operator.get_by_role("button", name="Save changes").click()
            operator.wait_for_url("**/breakdowns/*/")
            incident_id = int(operator.url.rstrip("/").split("/")[-1])
            expect(operator.locator('[data-mode="elapsed"]')).to_have_text(re.compile(r"2h 0[01]m"))
            tech_ctx, tech = session("north.tech")
            tech.goto(url + f"/breakdowns/{incident_id}/")
            tech.get_by_label("Repair started").fill(
                timezone.localtime(timezone.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
            )
            tech.get_by_label("Repair finished").fill(
                timezone.localtime(timezone.now() - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M")
            )
            tech.get_by_label("Root cause").fill("Loose coupling")
            tech.get_by_label("Action taken").fill("Tightened coupling and tested under load")
            tech.get_by_role("button", name="Save repair details").click()
            expect(tech.locator("[data-record-status]")).to_have_text("Closed")
            operator.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(operator.locator("[data-record-status]")).to_have_text("Closed")
            expect(operator.locator('[data-mode="elapsed"]')).to_have_attribute(
                "data-end", re.compile(r".+")
            )
            tech.goto(url + f"/pm/{task_id}/")
            tech.get_by_label("Completed at").fill(
                timezone.localtime(timezone.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")
            )
            tech.get_by_label("Work completed").fill("Browser acceptance: completed all checks")
            tech.get_by_role("button", name="Submit for approval").click()
            expect(tech.locator("[data-record-status]")).to_have_text("Awaiting approval")
            approver_ctx, approver = session("north.approver")
            approver.goto(url + f"/pm/{task_id}/")
            approver.get_by_label("Decision").select_option("reject")
            approver.get_by_label("Review notes").fill("Please add the lubricant grade")
            approver.get_by_role("button", name="Save review decision").click()
            expect(approver.locator("[data-record-status]")).to_have_text("Rejected")
            tech.reload()
            tech.get_by_label("Work completed").fill("Checks complete; ISO 68 lubricant used")
            tech.get_by_role("button", name="Submit for approval").click()
            expect(tech.locator("[data-record-status]")).to_have_text("Awaiting approval")
            approver.reload()
            approver.get_by_label("Decision").select_option("approve")
            approver.get_by_role("button", name="Save review decision").click()
            expect(approver.locator("[data-record-status]")).to_have_text("Approved")
            approver.screenshot(path=str(output / "approval-history.png"), full_page=True)
            operator.goto(url + "/runtime/new/")
            operator.locator('select[name="machine"]').select_option(str(machine_id))
            operator.get_by_label("Hours").fill("7.5")
            operator.get_by_role("button", name="Save changes").click()
            expect(operator.get_by_role("heading", name="Machine running hours", exact=True)).to_be_visible()
            operator_ctx.set_offline(True)
            expect(operator.locator("#connection-warning")).to_be_visible()
            operator_ctx.set_offline(False)
            expect(operator.locator("#connection-warning")).to_be_hidden(timeout=20000)
            assert not errors, errors
            browser.close()
            print(
                "PASS: desktop/mobile login, password change, all screens, XLSX, breakdown lifecycle, cross-device refresh, PM reject/resubmit/approve, runtime, offline recovery; no JS errors."
            )
    finally:
        if server:
            server.terminate()
            server.wait(timeout=20)
        connections.close_all()
        teardown_databases(original, verbosity=0)


if __name__ == "__main__":
    main()
