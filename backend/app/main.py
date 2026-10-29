"""LumiSteer FastAPI application.

Endpoints (all inputs validated with Pydantic, clear errors on failure):
  GET  /api/health
  GET  /api/config, POST /api/config
  POST /api/simulate
  POST /api/sweep
  POST /api/optimize
  POST /api/robust-optimize
  POST /api/compare
  POST /api/timeline
  POST /api/agent/run        (Server-Sent Events stream)
  POST /api/export/report, POST /api/export/csv

The app works fully without the LLM: every physics/optimization endpoint is
pure classical code; only /api/agent/run depends on the Nebius API, and it
falls back to a labelled demo-cache replay when the API is unavailable.
"""

from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()


import asyncio
import json
import os
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import ValidationError

from . import physics, optimizers, strategies, export
from .schemas import (SimConfig, SimResult, SweepResult, IRSAngles)
from .agent import (AgentSession, _observation, llm_configured, run_agent,
                    DEFAULT_MODEL, DEFAULT_BASE_URL)

app = FastAPI(title="LumiSteer", version="1.0.0")

allowed_origins = os.environ.get("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_STORE: SimConfig = SimConfig()


def _validated_config(payload) -> SimConfig:
    if payload is None or payload == {}:
        return CONFIG_STORE.model_copy(deep=True)
    if isinstance(payload, dict):
        merged = _merge_config(CONFIG_STORE.model_dump(), payload)
    else:
        merged = payload
    try:
        cfg = SimConfig.model_validate(merged)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"invalid config: {e}") from e
    cfg.clamp_vertical()
    return cfg


def _merge_config(base: dict, patch: dict) -> dict:
    """Deep-merge a partial config patch into the base config."""
    out = json.loads(json.dumps(base))
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge_config(out[k], v)
        elif v is None:
            continue
        else:
            out[k] = v
    return out


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_configured": llm_configured(),
        "model": os.environ.get("NEBIUS_MODEL", DEFAULT_MODEL),
        "base_url": os.environ.get("NEBIUS_BASE_URL", DEFAULT_BASE_URL),
    }


@app.get("/api/config")
def get_config():
    return CONFIG_STORE.model_dump(mode="json")


@app.post("/api/config")
def set_config(payload: dict):
    global CONFIG_STORE
    CONFIG_STORE = _validated_config(payload)
    return CONFIG_STORE.model_dump(mode="json")


# --------------------------------------------------------------- simulate ---

class SimulateRequest:
    pass


@app.post("/api/simulate", response_model=SimResult)
def api_simulate(body: dict):
    try:
        cfg = _validated_config(body)
        rx = body.get("rx_position")
        if rx is not None and (not isinstance(rx, list) or len(rx) != 3):
            raise HTTPException(422, "rx_position must be [x, y, z] numbers")
        angles = body.get("irs_angles")
        n = cfg.irs.n_elements if cfg.irs.enabled else 0
        if angles is None:
            angles = IRSAngles.zeros(max(n, 1))
        elif n:
            angles = IRSAngles.model_validate(angles).filled(n)
        else:
            angles = IRSAngles.zeros(1)
        target = rx if rx is not None else [cfg.receiver.position.x, cfg.receiver.position.y,
                                            cfg.receiver.position.z]
        res = physics.evaluate(cfg, angles.azimuth_deg, angles.elevation_deg, target)
        return SimResult(**res)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"simulate failed: {e}") from e


@app.post("/api/sweep", response_model=SweepResult)
def api_sweep(body: dict):
    try:
        cfg = _validated_config(body)
        res = int(body.get("resolution", 40))
        angles = _angles_for(body, cfg)
        sweep = physics.sweep(cfg, angles.azimuth_deg, angles.elevation_deg, res)
        return SweepResult(**sweep)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"sweep failed: {e}") from e


def _angles_for(body: dict, cfg: SimConfig) -> IRSAngles:
    n = cfg.irs.n_elements if cfg.irs.enabled else 0
    angles = body.get("irs_angles")
    if angles is None:
        return IRSAngles.zeros(max(n, 1))
    return IRSAngles.model_validate(angles).filled(n)


# -------------------------------------------------------------- optimize ---

@app.post("/api/optimize")
def api_optimize(body: dict):
    try:
        cfg = _validated_config(body)
        rx = body.get("rx_position")
        weights = body.get("objective_weights")
        include_power = bool(body.get("include_power", True))
        out = optimizers.optimize_irs(cfg, rx, objective_weights=weights,
                                      include_power=include_power)
        return out
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"optimize failed: {e}") from e


@app.post("/api/robust-optimize")
def api_robust(body: dict):
    try:
        cfg = _validated_config(body)
        rx = body.get("rx_position")
        radius = body.get("radius_m", 0.15)
        n_samples = int(body.get("n_samples", 10))
        out = optimizers.robust_optimize(cfg, rx, radius_m=float(radius),
                                         n_samples=n_samples)
        return out
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"robust-optimize failed: {e}") from e


@app.post("/api/baselines")
def api_baselines(body: dict):
    try:
        cfg = _validated_config(body)
        out = optimizers.baseline_configs(cfg)
        return {k: {"angles": v["angles"].model_dump(mode="json"),
                    "config": v["config"].model_dump(mode="json")} for k, v in out.items()}
    except Exception as e:
        raise HTTPException(400, f"baselines failed: {e}") from e


# --------------------------------------------------------------- compare ---

@app.post("/api/compare")
def api_compare(body: dict):
    try:
        cfg = _validated_config(body)
        scenario = body.get("scenario", "static")
        if scenario not in ("static", "moving", "blockage"):
            raise HTTPException(422, "scenario must be static | moving | blockage")
        heatmap_res = int(body.get("heatmap_resolution", 24))
        return strategies.run_comparison(cfg, scenario, heatmap_res)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"compare failed: {e}") from e


@app.post("/api/timeline")
def api_timeline(body: dict):
    try:
        cfg = _validated_config(body)
        return strategies.run_timeline(cfg)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"timeline failed: {e}") from e


# ----------------------------------------------------------------- agent ---

class AgentRunRequest:
    pass


@app.post("/api/agent/run")
async def api_agent_run(body: dict):
    """Runs the Nemotron agent loop and streams steps as Server-Sent Events.
    On API failure or missing key, replays the labelled demo cache."""
    try:
        cfg = _validated_config(body)
    except HTTPException:
        raise HTTPException(400, "invalid configuration for agent run")

    angles = body.get("irs_angles") or {}
    n = cfg.irs.n_elements if cfg.irs.enabled else 0
    try:
        if angles:
            angles = IRSAngles.model_validate(angles).filled(n)
        else:
            angles = IRSAngles.zeros(max(n, 1))
        session = AgentSession(cfg, {"azimuth_deg": angles.azimuth_deg,
                                     "elevation_deg": angles.elevation_deg},
                               history=body.get("telemetry_history"))
    except Exception as e:
        raise HTTPException(400, f"invalid agent input: {e}") from e

    scenario_note = body.get("scenario_note", "")

    async def gen():
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit(ev: dict):
            queue.put_nowait(ev)

        def run_llm():
            try:
                if not llm_configured():
                    raise RuntimeError("NEBIUS_API_KEY not configured")
                run_agent(session, emit, scenario_note)
                emit({"type": "done", "ts": None})
            except Exception as e:
                print(f"\n🔴 LIVE AGENT CRASHED: {type(e).__name__}: {e}\n")
                traceback.print_exc()
                emit({"type": "fallback_to_cache", "ts": None,
                      "data": {"error": f"{type(e).__name__}: {e}"}})
                for ev in replay_demo_cache():
                    emit(ev)
                emit({"type": "done", "ts": None, "cached": True})

        task = loop.run_in_executor(None, run_llm)
        while True:
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=180.0)
            except asyncio.TimeoutError:
                break
            payload = json.dumps(ev, default=str)
            yield f"data: {payload}\n\n"
            if ev.get("type") == "done":
                break
        await asyncio.wait([task], timeout=5.0)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


DEMO_CACHE_PATH = Path(__file__).parent / "demo_cache.json"


def replay_demo_cache():
    """Replay a saved agent run, clearly labelled as cached."""
    try:
        with open(DEMO_CACHE_PATH) as f:
            events = json.load(f)
    except Exception:
        events = [{"type": "note", "data": {"text": "Demo cache unavailable and no live LLM key configured."}}]
    out = []
    for ev in events:
        ev = dict(ev)
        ev["cached"] = True
        out.append(ev)
    out.append({"type": "cached_notice", "data": {
        "text": "Replaying a cached agent demo run (live LLM unavailable). "
                "Numbers come from a previously recorded tool session."}})
    return out


# ----------------------------------------------------------------- export ---

@app.post("/api/export/report", response_class=PlainTextResponse)
def api_report(body: dict):
    try:
        cfg_raw = _validated_config(body).model_dump(mode="json")
        md = export.report_markdown(cfg_raw, body.get("comparison"), body.get("agent_summary"))
        return md
    except Exception as e:
        raise HTTPException(400, f"report failed: {e}") from e


@app.post("/api/export/csv", response_class=PlainTextResponse)
def api_csv(body: dict):
    try:
        if body.get("comparison"):
            csv_text = export.comparison_to_csv(body["comparison"])
        else:
            cfg = _validated_config(body)
            angles = _angles_for(body, cfg)
            sweep = physics.sweep(cfg, angles.azimuth_deg, angles.elevation_deg,
                                  int(body.get("resolution", 40)))
            csv_text = export.sweep_to_csv(sweep)
        return csv_text
    except Exception as e:
        raise HTTPException(400, f"export failed: {e}") from e
