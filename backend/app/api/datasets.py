from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.api.common import DB, recent, require, save, serialize
from app.models.platform import (
    BatchRun,
    Case,
    CaseResult,
    Dataset,
    Experiment,
    Prompt,
    RegressionTest,
)
from app.schemas.platform import (
    CaseInput,
    DatasetInput,
    ExperimentInput,
    GateInput,
    PromptInput,
    RunInput,
)
from app.services.datasets import run_dataset

router = APIRouter(prefix="/api/v1")


@router.get("/prompts")
def prompts(db: DB):
    return recent(db, Prompt)


@router.post("/prompts", status_code=201)
def create_prompt(payload: PromptInput, db: DB):
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:name))"), {"name": payload.name})
    version = (
        db.scalar(select(func.max(Prompt.version)).where(Prompt.name == payload.name)) or 0
    ) + 1
    try:
        return save(db, Prompt(**payload.model_dump(), version=version))
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Concurrent version creation; retry") from exc


@router.get("/datasets")
def datasets(db: DB):
    return recent(db, Dataset)


@router.post("/datasets", status_code=201)
def create_dataset(payload: DatasetInput, db: DB):
    return save(db, Dataset(**payload.model_dump()))


@router.get("/datasets/{dataset_id}/cases")
def cases(dataset_id: str, db: DB):
    require(db, Dataset, dataset_id)
    return [
        serialize(c)
        for c in db.scalars(
            select(Case).where(Case.dataset_id == dataset_id).order_by(Case.created_at, Case.id)
        )
    ]


@router.post("/datasets/{dataset_id}/cases", status_code=201)
def add_case(dataset_id: str, payload: CaseInput, db: DB):
    require(db, Dataset, dataset_id)
    return save(db, Case(dataset_id=dataset_id, **payload.model_dump()))


@router.put("/cases/{case_id}")
def edit_case(case_id: str, payload: CaseInput, db: DB):
    row = require(db, Case, case_id)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    return save(db, row)


@router.post("/datasets/{dataset_id}/run", status_code=201)
async def run(dataset_id: str, payload: RunInput, db: DB):
    require(db, Dataset, dataset_id)
    return serialize(await run_dataset(dataset_id, payload, db))


@router.get("/dataset-runs")
def runs(db: DB):
    return recent(db, BatchRun)


@router.get("/dataset-runs/{run_id}")
def run_detail(run_id: str, db: DB):
    row = require(db, BatchRun, run_id)
    return {
        **serialize(row),
        "results": [
            serialize(r) for r in db.scalars(select(CaseResult).where(CaseResult.run_id == run_id))
        ],
    }


@router.get("/regressions")
def regressions(db: DB):
    return recent(db, RegressionTest)


@router.put("/datasets/{dataset_id}/baseline")
def baseline(dataset_id: str, payload: GateInput, db: DB):
    require(db, Dataset, dataset_id)
    run = require(db, BatchRun, payload.baseline_id)
    if run.dataset_id != dataset_id or run.errors:
        raise HTTPException(422, "Baseline must be an error-free run of this dataset")
    row = db.scalar(select(RegressionTest).where(RegressionTest.dataset_id == dataset_id))
    if row is None:
        row = RegressionTest(dataset_id=dataset_id)
    row.baseline_id = run.id
    row.thresholds = payload.model_dump(exclude={"baseline_id"})
    return save(db, row)


@router.get("/experiments")
def experiments(db: DB):
    return recent(db, Experiment)


@router.post("/experiments", status_code=201)
async def experiment(payload: ExperimentInput, db: DB):
    require(db, Dataset, payload.dataset_id)
    outputs = []
    for config in payload.configurations:
        run = await run_dataset(payload.dataset_id, config, db)
        outputs.append(
            {
                "run_id": run.id,
                "score": run.score,
                "latency_ms": run.latency_ms,
                "errors": run.errors,
                "passed": run.passed,
                "configuration": run.configuration,
                "metrics": run.metrics,
            }
        )
    return save(
        db,
        Experiment(
            name=payload.name,
            dataset_id=payload.dataset_id,
            configurations=[c.model_dump() for c in payload.configurations],
            results=outputs,
        ),
    )
