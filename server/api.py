from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import service
from .images import to_png_bytes
from .provider import ProviderClient, ProviderError
from .settings import SUBJECT_MODES, VERSION
from .skills import load_skills
from .util import dumps, loads

router = APIRouter()


class ProjectIn(BaseModel):
    name: str
    description: str = ""
    target_count: int = 100
    width: int = 1024
    height: int = 1024
    style_notes: str = ""
    subject_mode: str = "recognizable"
    skill_id: str | None = "character-collection"
    provider_id: str | None = None


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    target_count: int | None = None
    style_notes: str | None = None
    subject_mode: str | None = None
    skill_id: str | None = None
    provider_id: str | None = None


class ProviderIn(BaseModel):
    name: str
    base_url: str
    api_key: str = ""
    vision_model: str = ""
    text_model: str = ""
    image_model: str = ""
    edit_model: str = ""
    image_api: str = "openai_images"
    is_default: bool = False


class RefineIn(BaseModel):
    file_id: str
    instruction: str


class LockIn(BaseModel):
    file_id: str


class PlanIn(BaseModel):
    categories: list[dict] = Field(default_factory=list)
    rules: list[dict] = Field(default_factory=list)


class ContractIn(BaseModel):
    summary: str = ""
    palette: list[str] = Field(default_factory=list)
    line: str = ""
    lighting: str = ""
    texture: str = ""
    crop: str = ""
    identity: list[str] = Field(default_factory=list)
    forbid: list[str] = Field(default_factory=list)


class ApprovalIn(BaseModel):
    approved: bool


class NftPatch(BaseModel):
    locked: bool | None = None
    values: list[str] | None = None


class SampleIn(BaseModel):
    count: int = 24


def _fail(exc: Exception) -> None:
    status = 404 if isinstance(exc, KeyError) else 400
    raise HTTPException(status, str(exc)) from exc


def _start(project_id: str | None, kind: str, work) -> dict:
    try:
        job_id = service.create_job(project_id, kind)
    except (KeyError, ValueError) as exc:
        _fail(exc)

    def run() -> None:
        def progress(value: int, message: str) -> None:
            service.finish_job(job_id, "running", message, progress=value)

        service.finish_job(job_id, "running", "开始", progress=5)
        try:
            result = work(progress)
            service.finish_job(job_id, "done", "完成", result)
        except Exception as exc:
            service.finish_job(job_id, "error", str(exc), progress=100)

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


@router.get("/health")
def health() -> dict:
    return {"ok": True, "name": "Oriel NFT", "version": VERSION}


@router.get("/meta")
def meta() -> dict:
    return {"subject_modes": SUBJECT_MODES, "skills": load_skills(), "version": VERSION}


@router.get("/providers")
def list_providers() -> list[dict]:
    return [service.provider_view(row) for row in service.db.q("SELECT * FROM providers ORDER BY created_at")]


@router.post("/providers")
def create_provider(payload: ProviderIn) -> dict:
    try:
        return service.save_provider(payload.model_dump())
    except ValueError as exc:
        _fail(exc)


@router.put("/providers/{provider_id}")
def update_provider(provider_id: str, payload: ProviderIn) -> dict:
    try:
        return service.save_provider(payload.model_dump(), provider_id)
    except ValueError as exc:
        _fail(exc)


@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: str) -> dict:
    service.db.run("DELETE FROM providers WHERE id=?", (provider_id,))
    return {"ok": True}


@router.post("/providers/{provider_id}/models")
def provider_models(provider_id: str) -> dict:
    row = service.db.one("SELECT * FROM providers WHERE id=?", (provider_id,))
    if not row:
        raise HTTPException(404, "接口不存在")
    try:
        return {"models": ProviderClient(row).list_models()}
    except ProviderError as exc:
        _fail(exc)


@router.post("/providers/{provider_id}/test")
def provider_test(provider_id: str) -> dict:
    row = service.db.one("SELECT * FROM providers WHERE id=?", (provider_id,))
    if not row:
        raise HTTPException(404, "接口不存在")
    try:
        return {"reply": ProviderClient(row).ping(), "spends_credit": True}
    except ProviderError as exc:
        _fail(exc)


@router.get("/projects")
def list_projects() -> list[dict]:
    return [service.project_view(row) for row in service.db.q("SELECT * FROM projects ORDER BY updated_at DESC")]


@router.post("/projects")
def create_project(payload: ProjectIn) -> dict:
    try:
        return service.create_project(payload.model_dump())
    except ValueError as exc:
        _fail(exc)


@router.post("/sample-project")
def sample_project(payload: SampleIn) -> dict:
    count = min(100, max(4, payload.count))
    try:
        return service_build_sample(count)
    except Exception as exc:
        _fail(exc)


def service_build_sample(count: int) -> dict:
    from .sample import build_sample

    return build_sample(count=count, size=640)


@router.get("/projects/{project_id}")
def read_project(project_id: str) -> dict:
    try:
        return service.project_view(service.get_project(project_id))
    except KeyError as exc:
        _fail(exc)


@router.patch("/projects/{project_id}")
def patch_project(project_id: str, payload: ProjectPatch) -> dict:
    try:
        current = service.project_view(service.get_project(project_id))
        data = payload.model_dump(exclude_unset=True)
        return service.update_project(project_id, {**current, **data})
    except (KeyError, ValueError) as exc:
        _fail(exc)


@router.delete("/projects/{project_id}")
def remove_project(project_id: str) -> dict:
    try:
        service.delete_project(project_id)
    except KeyError as exc:
        _fail(exc)
    return {"ok": True}


@router.post("/projects/{project_id}/reference")
async def upload_reference(project_id: str, file: UploadFile = File(...)) -> dict:
    try:
        service.save_reference(project_id, await file.read())
        return service.project_view(service.get_project(project_id))
    except (KeyError, ValueError) as exc:
        _fail(exc)


@router.post("/projects/{project_id}/analyze")
def analyze(project_id: str) -> dict:
    return _start(project_id, "analyze", lambda progress: service.analyze_project(project_id, progress))


@router.put("/projects/{project_id}/analysis")
def save_analysis(project_id: str, payload: dict[str, Any]) -> dict:
    try:
        project = service.get_project(project_id)
        if project["style_contract_json"]:
            raise ValueError("主图已锁定，分析结果已固定")
        analysis = service.normalize_analysis(payload, payload.get("source") or "edited")
        service.touch(project_id, analysis_json=dumps(analysis), skill_id=analysis["suggested_skill"], status="analyzed")
        return service.project_view(service.get_project(project_id))
    except (KeyError, ValueError) as exc:
        _fail(exc)


@router.post("/projects/{project_id}/concepts")
def concepts(project_id: str) -> dict:
    return _start(project_id, "concepts", lambda progress: service.generate_concepts(project_id, progress))


@router.post("/projects/{project_id}/refine")
def refine(project_id: str, payload: RefineIn) -> dict:
    return _start(
        project_id,
        "refine",
        lambda progress: service.refine_concept(project_id, payload.file_id, payload.instruction, progress),
    )


@router.post("/projects/{project_id}/lock")
def lock(project_id: str, payload: LockIn) -> dict:
    return _start(project_id, "lock", lambda progress: service.lock_master(project_id, payload.file_id, progress))


@router.put("/projects/{project_id}/contract")
def save_contract(project_id: str, payload: ContractIn) -> dict:
    try:
        return service.save_style_contract(project_id, payload.model_dump())
    except (KeyError, ValueError) as exc:
        _fail(exc)


@router.post("/projects/{project_id}/cutout")
def cutout(project_id: str, use_model: bool = False) -> dict:
    return _start(project_id, "cutout", lambda progress: service.separate_subject(project_id, use_model, progress))


@router.post("/projects/{project_id}/plan")
def plan(project_id: str) -> dict:
    return _start(project_id, "plan", lambda progress: service.plan_traits(project_id, progress))


@router.put("/projects/{project_id}/plan")
def put_plan(project_id: str, payload: PlanIn) -> dict:
    try:
        service.save_plan(project_id, payload.model_dump())
        return service.project_view(service.get_project(project_id))
    except (KeyError, ValueError) as exc:
        _fail(exc)


@router.post("/projects/{project_id}/assets")
def assets(project_id: str, value_id: str | None = None) -> dict:
    return _start(project_id, "assets", lambda progress: service.generate_assets(project_id, progress, value_id))


@router.post("/projects/{project_id}/values/{value_id}/approval")
def approval(project_id: str, value_id: str, payload: ApprovalIn) -> dict:
    try:
        service.set_asset_approval(project_id, value_id, payload.approved)
        return service.project_view(service.get_project(project_id))
    except (KeyError, ValueError) as exc:
        _fail(exc)


@router.post("/projects/{project_id}/values/{value_id}/upload")
async def upload_asset(project_id: str, value_id: str, file: UploadFile = File(...)) -> dict:
    try:
        service.attach_upload_asset(project_id, value_id, await file.read())
        return service.project_view(service.get_project(project_id))
    except (KeyError, ValueError) as exc:
        _fail(exc)


@router.post("/projects/{project_id}/trial")
def trial(project_id: str) -> dict:
    return _start(project_id, "trial", lambda progress: service.generate_trial(project_id, progress))


@router.post("/projects/{project_id}/trial/approve")
def approve_trial(project_id: str) -> dict:
    try:
        return service.approve_trial(project_id)
    except (KeyError, ValueError) as exc:
        _fail(exc)


@router.post("/projects/{project_id}/collection")
def collection(project_id: str, count: int | None = None) -> dict:
    project = service.db.one("SELECT target_count FROM projects WHERE id=?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")
    total = count or project["target_count"]
    return _start(project_id, "collection", lambda progress: service.mint_collection(project_id, int(total), progress))


@router.get("/projects/{project_id}/nfts")
def list_nfts(project_id: str, offset: int = 0, limit: int = 60) -> dict:
    rows = service.db.q(
        "SELECT * FROM nfts WHERE project_id=? ORDER BY token_id LIMIT ? OFFSET ?",
        (project_id, min(200, max(1, limit)), max(0, offset)),
    )
    total = service.db.one("SELECT COUNT(*) AS n FROM nfts WHERE project_id=?", (project_id,))
    return {"total": total["n"] if total else 0, "items": [service.nft_view(row) for row in rows]}


@router.post("/projects/{project_id}/nfts/{nft_id}/reroll")
def reroll(project_id: str, nft_id: str) -> dict:
    try:
        return service.reroll_nft(project_id, nft_id)
    except (KeyError, ValueError) as exc:
        _fail(exc)


@router.patch("/projects/{project_id}/nfts/{nft_id}")
def patch_nft(project_id: str, nft_id: str, payload: NftPatch) -> dict:
    try:
        return service.update_nft(project_id, nft_id, payload.model_dump(exclude_unset=True))
    except (KeyError, ValueError) as exc:
        _fail(exc)


@router.get("/projects/{project_id}/stats")
def stats(project_id: str) -> dict:
    try:
        return service.collection_stats(project_id)
    except KeyError as exc:
        _fail(exc)


@router.post("/projects/{project_id}/export")
def export_project(project_id: str) -> FileResponse:
    try:
        path = service.export_zip(project_id)
    except (KeyError, ValueError) as exc:
        _fail(exc)
    return FileResponse(path, filename="oriel-collection.zip", media_type="application/zip")


@router.get("/jobs/{job_id}")
def read_job(job_id: str) -> dict:
    row = service.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not row:
        raise HTTPException(404, "任务不存在")
    return service.job_view(row)


@router.get("/files/{file_id}")
def read_file(file_id: str) -> FileResponse:
    try:
        return FileResponse(service.safe_file(file_id))
    except KeyError as exc:
        _fail(exc)


@router.get("/nfts/{nft_id}/image")
def read_nft(nft_id: str) -> FileResponse:
    try:
        return FileResponse(service.safe_nft_image(nft_id))
    except KeyError as exc:
        _fail(exc)


@router.post("/projects/{project_id}/preview")
def preview(project_id: str, payload: dict[str, Any]) -> Response:
    try:
        project = service.get_project(project_id)
        plan = service.normalize_plan(loads(project.get("plan_json"), {}))
        values = payload.get("values") or []
        lookup = {value["id"]: (category, value) for category in plan["categories"] for value in category["values"]}
        choice = {}
        for value_id in values:
            category, value = lookup[value_id]
            choice[category["id"]] = value
        image = service.render_choice(project, plan, choice, service._cutout_image(project_id))
        return Response(content=to_png_bytes(image), media_type="image/png")
    except Exception as exc:
        _fail(exc if isinstance(exc, (KeyError, ValueError)) else ValueError(str(exc)))
