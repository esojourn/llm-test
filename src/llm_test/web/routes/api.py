"""Test execution API with SSE progress streaming."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import EndpointConfig, ProbeConfig
from ...client import EndpointClient, EndpointUnreachableError
from ...probes import BaseProbe, ProbeResult, get_all_probes
from ...scoring import compute_verdict
from ..auth import decode_token
from ..database import get_db
from ..models import TestReport
from ..schemas import TestRequest

router = APIRouter(tags=["test"])


def _is_test_mode() -> bool:
    return os.environ.get("LLM_TEST_MODE") == "1"


def _load_presets() -> list[dict]:
    path = Path("config/presets.yaml")
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text())
    return data.get("presets", []) if data else []


@router.get("/presets")
async def get_presets():
    if not _is_test_mode():
        raise HTTPException(404, "Not available")
    presets = _load_presets()
    # Mask API keys — only send last 4 chars
    safe = []
    for p in presets:
        safe.append({
            "name": p["name"],
            "base_url": p["base_url"],
            "api_key_masked": "..." + p.get("api_key", "")[-4:],
            "provider": p.get("provider", "anthropic_compatible"),
        })
    return {"presets": safe}


@router.post("/presets/apply")
async def apply_preset(request: Request):
    if not _is_test_mode():
        raise HTTPException(404, "Not available")
    body = await request.json()
    index = body.get("index")
    presets = _load_presets()
    if index is None or index < 0 or index >= len(presets):
        raise HTTPException(400, "Invalid preset index")
    p = presets[index]
    return {
        "base_url": p["base_url"],
        "api_key": p.get("api_key", ""),
        "provider": p.get("provider", "anthropic_compatible"),
    }

# In-memory store for active test sessions
_active_tests: dict[str, asyncio.Queue] = {}


def _get_current_user(request: Request) -> dict | None:
    token = request.cookies.get("token") or request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not token:
        return None
    return decode_token(token)


def _serialize_probe_result(r: ProbeResult) -> dict:
    return {
        "probe_name": r.probe_name,
        "score": r.score,
        "confidence": r.confidence,
        "details": r.details,
    }


@router.post("/test")
async def start_test(req: TestRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user = _get_current_user(request)

    target_config = EndpointConfig(
        name="web_test",
        provider=req.provider,
        api_key_inline=req.api_key,
        base_url=req.base_url,
        model=req.model,
    )

    test_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _active_tests[test_id] = queue

    asyncio.create_task(_run_test(test_id, target_config, queue, db, user))

    return {"test_id": test_id}


async def _run_test(
    test_id: str,
    target_config: EndpointConfig,
    queue: asyncio.Queue,
    db: AsyncSession,
    user: dict | None,
):
    try:
        target = EndpointClient(target_config)

        # Pre-flight connectivity check — fail fast with a clear message
        await queue.put({"type": "preflight", "message": "正在检查端点连通性..."})
        try:
            await target.preflight_check()
        except EndpointUnreachableError as e:
            await queue.put({"type": "error", "message": f"端点不可用: {e}"})
            return

        # Load baseline cache if available
        from pathlib import Path
        from ...client import CachedEndpointClient
        from ...cache import load_cache

        baseline = None
        cache_path = Path("cache/baseline.json")
        if cache_path.exists():
            cache = load_cache(cache_path)
            baseline = CachedEndpointClient(cache)

        # Load default probe config
        from ...config import load_config
        try:
            config = load_config()
        except Exception:
            config = None

        available_probes = get_all_probes()
        probes: dict[str, BaseProbe] = {}
        weights: dict[str, float] = {}
        for name, probe in available_probes.items():
            if config:
                pc = config.probes.get(name, ProbeConfig())
                if not pc.enabled:
                    continue
                weights[name] = pc.weight
            else:
                weights[name] = 1.0
            probes[name] = probe

        total = len(probes)
        await queue.put({"type": "start", "total": total, "probes": list(probes.keys())})

        results: list[ProbeResult] = []
        for i, (probe_name, probe) in enumerate(probes.items()):
            await queue.put({"type": "probe_start", "probe": probe_name, "index": i})

            probe_cfg = config.probes.get(probe_name, ProbeConfig()) if config else ProbeConfig()
            extra = probe_cfg.model_dump(exclude={"enabled", "weight"})

            try:
                result = await probe.run(target, baseline, extra)
                results.append(result)
            except Exception as e:
                result = ProbeResult(probe_name=probe_name, score=0.5, confidence=0.1, details={"error": str(e)})
                results.append(result)

            await queue.put({
                "type": "probe_done",
                "probe": probe_name,
                "index": i,
                "result": _serialize_probe_result(result),
            })

        confidence_threshold = config.scoring.confidence_threshold if config else 0.75
        verdict = compute_verdict(results, weights, confidence_threshold)

        # Save report
        report = TestReport(
            id=test_id,
            user_id=user["sub"] if user else None,
            provider=target_config.provider,
            base_url=target_config.base_url,
            model=target_config.model,
            overall_score=verdict.overall_score,
            classification=verdict.classification,
            explanation=verdict.explanation,
            probe_results=[_serialize_probe_result(r) for r in results],
        )
        db.add(report)
        await db.commit()

        await queue.put({
            "type": "complete",
            "report_id": test_id,
            "overall_score": verdict.overall_score,
            "classification": verdict.classification,
            "explanation": verdict.explanation,
            "probe_scores": verdict.probe_scores,
        })

    except Exception as e:
        await queue.put({"type": "error", "message": str(e)})
    finally:
        await queue.put(None)


@router.get("/test/{test_id}/stream")
async def test_stream(test_id: str):
    queue = _active_tests.get(test_id)
    if not queue:
        raise HTTPException(404, "测试不存在或已过期")

    async def event_generator():
        try:
            while True:
                msg = await asyncio.wait_for(queue.get(), timeout=600)
                if msg is None:
                    break
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'type': 'error', 'message': '测试超时'})}\n\n"
        finally:
            _active_tests.pop(test_id, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
