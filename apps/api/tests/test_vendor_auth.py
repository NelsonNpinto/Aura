import uuid

import httpx
import pytest
from sqlalchemy import text

from app.core.db import system_tx
from app.main import create_app


@pytest.mark.db
async def test_vendor_assignment_refreshes_stale_roles_and_revocation_blocks_access(mint, org_id):
    admin = "admin-" + uuid.uuid4().hex
    vendor = "vendor-" + uuid.uuid4().hex
    email = vendor + "@example.invalid"
    async with system_tx() as session:
        await session.execute(
            text(
                "INSERT INTO auth.organization (id,name,slug,\"createdAt\") VALUES (:id,'Procurement test',:id,now())"
            ),
            {"id": org_id},
        )
        for uid, address in ((admin, admin + "@example.invalid"), (vendor, email)):
            await session.execute(
                text(
                    'INSERT INTO auth."user" (id,name,email,"emailVerified","createdAt","updatedAt") VALUES (:id,\'Synthetic test user\',:email,false,now(),now())'
                ),
                {"id": uid, "email": address},
            )
        await session.execute(
            text(
                'INSERT INTO auth.member (id,"organizationId","userId",role,"createdAt") VALUES (:id,:o,:u,\'admin\',now())'
            ),
            {"id": str(uuid.uuid4()), "o": org_id, "u": admin},
        )
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        admin_headers = {"authorization": "Bearer " + mint(org_id, ["admin"], user_id=admin)}
        for _ in range(2):
            response = await client.post(
                "/api/v1/procurement/members",
                headers=admin_headers,
                json={"email": email, "role": "vendor", "vendor_id": "ACME"},
            )
            assert response.status_code == 200, response.text
        async with system_tx() as session:
            count = (
                await session.execute(
                    text(
                        'SELECT count(*) FROM auth.member WHERE "organizationId"=:o AND "userId"=:u'
                    ),
                    {"o": org_id, "u": vendor},
                )
            ).scalar_one()
            assert count == 1
        # Simulate a still-valid JWT that held broader roles before the assignment.
        headers = {"authorization": "Bearer " + mint(org_id, ["admin"], user_id=vendor)}
        assert (await client.get("/api/v1/me", headers=headers)).json()["roles"] == ["vendor"]
        assert (await client.get("/api/v1/runs", headers=headers)).status_code == 403
        assert (await client.get("/api/v1/knowledge/documents", headers=headers)).status_code == 403
        assert (await client.get("/api/v1/procurement/cases", headers=headers)).status_code == 200
        async with system_tx() as session:
            await session.execute(
                text('DELETE FROM auth.member WHERE "organizationId"=:o AND "userId"=:u'),
                {"o": org_id, "u": vendor},
            )
        assert (await client.get("/api/v1/procurement/cases", headers=headers)).status_code == 403
