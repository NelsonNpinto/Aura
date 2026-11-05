"""Create schema erp and (re)seed one org from the generator's world.json. Idempotent.

    python -m erp_mock.seed --org demo --world ../../evals/datasets/world
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path

from sqlalchemy import text

from erp_mock.tools import _bank_hash, engine

SCHEMA = Path(__file__).with_name("schema.sql")
ORG_TABLES = ["payments", "posted_invoices", "vendor_change_requests", "grn_lines", "goods_receipts", "po_lines",
              "purchase_orders", "contracts", "cost_centers", "gl_accounts", "employees", "vendor_bank_accounts", "vendors"]


async def bootstrap() -> None:
    async with engine().begin() as c:
        sql = "\n".join(ln for ln in SCHEMA.read_text().splitlines() if not ln.strip().startswith("--"))
        for stmt in sql.split(";"):
            if stmt.strip():
                await c.execute(text(stmt))


async def seed(org: str, world_dir: Path) -> dict[str, int]:
    w = json.loads((world_dir / "world.json").read_text())
    banks = json.loads((world_dir / "bank_accounts.json").read_text())
    d = date.fromisoformat
    async with engine().begin() as c:
        for t in ORG_TABLES:
            await c.execute(text(f"DELETE FROM erp.{t} WHERE org_id=:o"), {"o": org})  # noqa: S608 constant names
        for v in w["vendors"]:
            await c.execute(text(
                "INSERT INTO erp.vendors (org_id,id,name,aliases,tax_id,category,currency,country,address,payment_terms_days,"
                "cost_center,created_by,contract_id,status) VALUES (:o,:id,:name,CAST(:aliases AS jsonb),:tax,:cat,:cur,:country,"
                ":addr,:terms,:cc,:by,:k,:st)"),
                {"o": org, "id": v["id"], "name": v["name"], "aliases": json.dumps(v["aliases"]), "tax": v["tax_id"],
                 "cat": v["category"], "cur": v["currency"], "country": v["country"], "addr": v["address"],
                 "terms": v["payment_terms_days"], "cc": v["cost_center"], "by": v["created_by"], "k": v["contract_id"],
                 "st": v["status"]})
            b = banks[v["id"]]
            await c.execute(text(
                "INSERT INTO erp.vendor_bank_accounts (org_id,vendor_id,account_hash,last4,effective_from,changed_by)"
                " VALUES (:o,:v,:h,:l,:d,:by)"),
                {"o": org, "v": v["id"], "h": _bank_hash(b["routing"], b["account_number"]), "l": b["account_number"][-4:],
                 "d": d(v["bank"]["effective_from"]), "by": v["bank"]["changed_by"]})
        for e in w["employees"]:
            await c.execute(text("INSERT INTO erp.employees (org_id,id,name,email,role,bank_hash,bank_last4) VALUES (:o,:id,:n,:e,:r,:h,:l)"),
                            {"o": org, "id": e["id"], "n": e["name"], "e": e["email"], "r": e["role"], "h": e["bank_hash"], "l": e["bank_last4"]})
        for g in w["gl_accounts"]:
            await c.execute(text("INSERT INTO erp.gl_accounts (org_id,code,name,guidance) VALUES (:o,:c,:n,:g)"),
                            {"o": org, "c": g["code"], "n": g["name"], "g": g["guidance"]})
        for cc in w["cost_centers"]:
            await c.execute(text("INSERT INTO erp.cost_centers (org_id,code,name) VALUES (:o,:c,:n)"), {"o": org, "c": cc["code"], "n": cc["name"]})
        for k in w["contracts"]:
            await c.execute(text("INSERT INTO erp.contracts (org_id,id,vendor_id,description,monthly_cap_minor,currency,start_date,end_date)"
                                 " VALUES (:o,:id,:v,:d,:cap,:cur,:s,:e)"),
                            {"o": org, "id": k["id"], "v": k["vendor_id"], "d": k["description"], "cap": k["monthly_cap_minor"],
                             "cur": k["currency"], "s": d(k["start"]), "e": d(k["end"])})
        for p in w["purchase_orders"]:
            await c.execute(text("INSERT INTO erp.purchase_orders (org_id,po_number,vendor_id,currency,order_date,requester_id,status)"
                                 " VALUES (:o,:p,:v,:c,:d,:r,:s)"),
                            {"o": org, "p": p["po_number"], "v": p["vendor_id"], "c": p["currency"], "d": d(p["order_date"]),
                             "r": p["requester_id"], "s": p["status"]})
            for ln in p["lines"]:
                await c.execute(text("INSERT INTO erp.po_lines (org_id,po_number,line_no,description,quantity,uom,unit_price_minor,"
                                     "gl_account,cost_center,is_service) VALUES (:o,:p,:l,:d,:q,:u,:pr,:gl,:cc,:s)"),
                                {"o": org, "p": p["po_number"], "l": ln["line_no"], "d": ln["description"], "q": ln["quantity"],
                                 "u": ln["uom"], "pr": ln["unit_price_minor"], "gl": ln["gl_account"], "cc": ln["cost_center"],
                                 "s": ln["is_service"]})
            # Services are confirmed by the requester: model as a receipt so the match engine sees it.
            svc = [ln for ln in p["lines"] if ln["is_service"]]
            if svc:
                g = f"SVC-{p['po_number']}"
                await c.execute(text("INSERT INTO erp.goods_receipts (org_id,grn_number,po_number,received_date) VALUES (:o,:g,:p,:d)"),
                                {"o": org, "g": g, "p": p["po_number"], "d": d(p["order_date"])})
                for ln in svc:
                    await c.execute(text("INSERT INTO erp.grn_lines (org_id,grn_number,po_line,quantity) VALUES (:o,:g,:l,:q)"),
                                    {"o": org, "g": g, "l": ln["line_no"], "q": ln["quantity"]})
        for g in w["goods_receipts"]:
            await c.execute(text("INSERT INTO erp.goods_receipts (org_id,grn_number,po_number,received_date) VALUES (:o,:g,:p,:d)"),
                            {"o": org, "g": g["grn_number"], "p": g["po_number"], "d": d(g["received_date"])})
            for ln in g["lines"]:
                await c.execute(text("INSERT INTO erp.grn_lines (org_id,grn_number,po_line,quantity) VALUES (:o,:g,:l,:q)"),
                                {"o": org, "g": g["grn_number"], "l": ln["po_line"], "q": ln["quantity"]})
    return {"vendors": len(w["vendors"]), "purchase_orders": len(w["purchase_orders"])}


async def main_async(orgs: list[str], world: Path) -> None:
    await bootstrap()
    for o in orgs:
        print(o, await seed(o, world))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", action="append", default=None)
    ap.add_argument("--world", default=str(Path(__file__).resolve().parents[3] / "evals" / "datasets" / "world"))
    a = ap.parse_args()
    asyncio.run(main_async(a.org or ["demo"], Path(a.world)))


if __name__ == "__main__":
    main()
