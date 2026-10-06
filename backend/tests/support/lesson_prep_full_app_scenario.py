"""Reuse the frozen full-app isolation/auth/migration/recording harness."""
import asyncio
from hashlib import sha256
import json
import shutil

from teacher_work_full_app_scenario import (
    Scenario, ROOT, OWNER, OTHER, STUDENT, GUARDS, app, database, httpx, event, text,
)
from tests.support.courseware_synthetic import write_pdf, PDF_PAGES
from app.models.domain_record import DomainRecord
from sqlalchemy import select


class DraftScenario(Scenario):
    async def run(self):
        try:
            source = ROOT / "sources/AI_technology/synthetic.pdf"
            write_pdf(source)
            self.facts["synthetic_document"] = dict(path="AI_technology/synthetic.pdf",
                sha256=sha256(source.read_bytes()).hexdigest(), byte_size=source.stat().st_size,
                text=PDF_PAGES, real_courseware_verified=False)
            async with app.router.lifespan_context(app):
                assert app.state.git_coach_worker is None
                self.facts["real_lifespan_entered"] = True
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url="http://synthetic.local") as self.client:
                    await self.login()
                    base = "/api/teacher/lesson-prep"
                    resources = await self.call("GET", base + "/resources")
                    assert resources.status_code == 200, resources.text
                    resource = resources.json()["data"]["resources"][0]
                    search = await self.call("POST", base + "/search",
                        body=dict(query="utility functions", resource_ids=[resource["id"]]))
                    assert search.status_code == 200, search.text
                    match = search.json()["data"]["matches"][0]
                    assert match["page"] == 1 and "Utility functions" in match["excerpt"]
                    payload = dict(title="Synthetic draft A", topic="Synthetic topic", duration_minutes=45,
                                   resource_ids=[resource["id"]], content=dict(objectives=["Synthetic objective"]))
                    created = await self.call("POST", base + "/drafts", body=payload)
                    assert created.status_code == 200, created.text
                    draft = created.json()["data"]
                    draft_id = draft["draft_id"]
                    with database.engine.connect() as connection:
                        stored = connection.execute(select(DomainRecord.__table__).where(
                            DomainRecord.module == "teacher_lesson_prep", DomainRecord.record_key == draft_id)).mappings().one()
                        assert stored["owner_id"] == OWNER
                        assert json.loads(stored["payload"])["title"] == payload["title"]
                        self.facts["independent_saved_row"] = dict(stored)
                    listed = await self.call("GET", base + "/drafts")
                    detail = await self.call("GET", base + "/drafts/" + draft_id)
                    assert listed.status_code == detail.status_code == 200
                    assert listed.json()["data"]["total"] == 1
                    assert detail.json()["data"]["title"] == payload["title"]
                    foreign_list = await self.call("GET", base + "/drafts", owner=OTHER)
                    foreign_read = await self.call("GET", base + "/drafts/" + draft_id, owner=OTHER)
                    foreign_write = await self.call("POST", base + "/drafts", owner=OTHER,
                        body={**payload, "draft_id": draft_id, "title": "Synthetic foreign overwrite"})
                    assert foreign_list.status_code == 200 and foreign_list.json()["data"]["drafts"] == []
                    assert foreign_read.status_code == foreign_write.status_code == 404
                    for method, path, body in (("GET", base + "/drafts", None),
                            ("GET", base + "/drafts/" + draft_id, None), ("POST", base + "/drafts", payload)):
                        response = await self.call(method, path, body=body, owner=STUDENT)
                        assert response.status_code == 403
                    invalid = await self.call("POST", base + "/drafts", body=payload, token="synthetic-invalid-token")
                    assert invalid.status_code == 401
                    updated = await self.call("POST", base + "/drafts",
                        body={**payload, "draft_id": draft_id, "title": "Synthetic edited draft B"})
                    assert updated.status_code == 200 and updated.json()["data"]["title"] == "Synthetic edited draft B"
                    with database.engine.connect() as connection:
                        rows = connection.execute(select(DomainRecord.__table__).where(
                            DomainRecord.module == "teacher_lesson_prep")).mappings().all()
                        assert len(rows) == 1 and rows[0]["owner_id"] == OWNER
                        assert json.loads(rows[0]["payload"])["title"] == "Synthetic edited draft B"
                        self.facts["independent_final_rows"] = [dict(row) for row in rows]
            assert not self.checked and not self.provider_calls
            assert GUARDS["env_reads_denied"] == GUARDS["tcp_connections_denied"] == 0
            self.facts["real_lifespan_exited"] = True
            self.facts["completed"] = True
        finally:
            event.remove(database.engine, "checkout", self.checkout)
            event.remove(database.engine, "checkin", self.checkin)
            database.engine.dispose()
            storage = ROOT / "private-storage"
            if storage.exists():
                shutil.rmtree(storage)
            self.facts["private_storage_removed"] = not storage.exists()
            self.facts["guards"] = dict(GUARDS)
            (ROOT / "scenario.json").write_text(json.dumps(self.facts, ensure_ascii=False, indent=2, default=str) + "\n")


if __name__ == "__main__":
    asyncio.run(DraftScenario("legacy_drafts").run())
