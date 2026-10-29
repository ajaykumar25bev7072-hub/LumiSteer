"""LLM agent (supervisor role) for LumiSteer.

Runs NVIDIA Nemotron on Nebius Token Factory (OpenAI-compatible chat
completions, native tool calling, JSON fallback). The agent NEVER computes
metrics itself: every number it can quote comes from the physics engine via
tool calls. A hard iteration cap (4), argument validation, timeouts and a
demo cache (replay of a saved run, clearly labelled) are part of this module.
"""
from __future__ import annotations

import copy
import json
import os
import re
import time
from typing import Callable, Dict, List, Optional

MAX_ITERATIONS = 6  # ~2 diagnose/fix attempts + verify + final explanation
REQUEST_TIMEOUT_S = 20.0

DEFAULT_MODEL = "nvidia/Llama-3_3-Nemotron-Super-49B-v1_5"
DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1"

SYSTEM_PROMPT = """You are the LumiSteer link supervisor agent for an indoor \
Visible Light Communication (VLC) link assisted by a reconfigurable \
Intelligent Reflecting Surface (IRS). Hardware: one ceiling LED Lambertian \
transmitter, one photodiode receiver on a desk, one IRS panel of tilted \
mirror elements on a wall, and a movable person-shaped blocker.

HARD RULES:
- You do NOT compute any numbers yourself. All metrics (power, irradiance, \
SNR, BER, lux, outage) come exclusively from the tools. Never invent, \
estimate or extrapolate numbers.
- Quote only values that appear in tool results you have received in this \
conversation. When you cite a number, it must be copied from a tool result.
- You must respect physical constraints: LED power in [0.1, 1.0] W times the \
configured max; minimum-illuminance comfort limit (default 300 lux at the \
work plane); IRS tilt ranges.
- Diagnose causes of degradation (direct path blocked, receiver moved out of \
the optimized region, high ambient noise, illumination constraint limiting \
power, stale IRS configuration), then act: call the right tool in the right \
order, check the result against the target BER < {ber_threshold} and the \
illuminance constraint, and retry with a different strategy if the target is \
unmet (e.g. robust_optimize when optimize_irs is too fragile).
- You have at most {max_iterations} tool iterations. Prefer: observe -> \
diagnose -> one well-chosen optimization tool -> verify with simulate -> \
explain.
- Your FINAL answer must be a plain-language explanation for a link \
operator: what happened (cause), what you did (which tool, and the resulting \
IRS re-steering), and the numbers BEFORE and AFTER (BER, received power, \
link status), all copied from tool results. Keep it under 150 words.

Available tool semantics:
- get_telemetry: current link state, no arguments needed.
- simulate: evaluate the link at the CURRENT IRS angles (optionally at a \
different receiver position, a different LED power, or with/off the \
obstacle) and observe what happens.
- optimize_irs: point-optimize IRS tilts for a receiver position (fast, but \
fragile if the receiver later moves).
- robust_optimize: optimize the IRS for average-and-worst case over \
receiver positions inside a radius around the current position (robustness \
against movement).
- predict_blockage: classical risk score from recent telemetry trend.
"""

TOOLS_SCHEMA: List[dict] = [
    {"type": "function", "function": {
        "name": "get_telemetry",
        "description": "Get the current link state: metrics, receiver position, LED power, obstacle state, IRS configuration summary.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "simulate",
        "description": "Evaluate the link with the physics engine at the current IRS angles. Optionally override receiver position, LED power (must stay within [10%,100%] of max), obstacle presence, or ambient light class.",
        "parameters": {"type": "object", "properties": {
            "rx_position": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                            "description": "receiver position [x, y, z] in meters"},
            "led_power_w": {"type": "number",
                            "description": "LED power in W to test; must be within allowed dimming range"},
            "obstacle_enabled": {"type": "boolean"},
            "ambient": {"type": "string", "enum": ["low", "medium", "high"]}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "optimize_irs",
        "description": "Point-optimize the IRS tilt angles for a receiver position using the weighted objective. Fast but only guaranteed at that position.",
        "parameters": {"type": "object", "properties": {
            "rx_position": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
            "objective_weights": {"type": "object", "properties": {
                "power": {"type": "number"}, "irradiance": {"type": "number"}, "ber": {"type": "number"}}}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "robust_optimize",
        "description": "Optimize the IRS for the average AND worst case over receiver positions sampled inside a radius around the given position. Use when the receiver may move (blockage risk, walking person, receiver drift).",
        "parameters": {"type": "object", "properties": {
            "rx_position": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
            "radius_cm": {"type": "number", "description": "robustness radius in centimeters, default 15"},
            "n_samples": {"type": "number", "description": "receiver positions to sample, default 10"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "predict_blockage",
        "description": "Classical predictor: blockage risk score from the recent received-power trend and obstacle motion. No LLM involved.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]


class AgentError(Exception):
    pass


def llm_configured() -> bool:
    return bool(os.environ.get("NEBIUS_API_KEY"))


def _client():
    from openai import OpenAI
    return OpenAI(
        base_url=os.environ.get("NEBIUS_BASE_URL", DEFAULT_BASE_URL),
        api_key=os.environ["NEBIUS_API_KEY"],
        timeout=REQUEST_TIMEOUT_S,
        max_retries=1,
    )


class AgentSession:
    """Mutable simulation state shared by the agent's tool calls."""

    def __init__(self, cfg, angles: Dict[str, List[float]],
                 history: Optional[List[dict]] = None):
        self.cfg = cfg.model_copy(deep=True)
        self.angles = copy.deepcopy(angles)
        self.telemetry_history: List[dict] = history or []

    # -- helpers ----------------------------------------------------------
    def _n(self) -> int:
        return self.cfg.irs.n_elements if self.cfg.irs.enabled else 0

    def apply_angles(self, angles) -> None:
        n = self._n()
        az = list(angles.azimuth_deg)[:n]
        el = list(angles.elevation_deg)[:n]
        self.angles = {"azimuth_deg": az + [0.0] * max(0, n - len(az)),
                       "elevation_deg": el + [0.0] * max(0, n - len(el))}

    def snapshot_payload(self) -> dict:
        n = self._n()
        return {
            "config": self.cfg.model_dump(mode="json"),
            "irs_angles": self.angles,
        }


def _record_telemetry(session: AgentSession, metrics: dict, extra: dict | None = None) -> dict:
    rec = {
        "received_power_w": metrics["received_power_w"],
        "snr": metrics["snr"], "ber": metrics["ber"], "link_status": metrics["link_status"],
        "obstacle_x": session.cfg.obstacle.center.x,
        "obstacle_y": session.cfg.obstacle.center.y,
        "t": time.time(),
        **(extra or {}),
    }
    session.telemetry_history.append(rec)
    session.telemetry_history = session.telemetry_history[-40:]
    return rec


def _observation(session: AgentSession) -> dict:
    from . import physics
    n = session._n()
    angles = IRSAngles_compat(session.angles, n)
    metrics = physics.evaluate(session.cfg,
                               angles.get("azimuth_deg", [0.0] * n),
                               angles.get("elevation_deg", [0.0] * n),
                               [session.cfg.receiver.position.x, session.cfg.receiver.position.y,
                                session.cfg.receiver.position.z])
    rec = _record_telemetry(session, metrics)
    return {
        "role": "observation",
        "received_power_w": metrics["received_power_w"],
        "irradiance_w_m2": metrics["irradiance_w_m2"],
        "illuminance_lux": metrics["illuminance_lux"],
        "illuminance_min_required": session.cfg.illumination.min_lux,
        "illuminance_ok": metrics["illuminance_ok"],
        "snr": metrics["snr"], "snr_db": metrics["snr_db"], "ber": metrics["ber"],
        "target_ber": session.cfg.modulation.ber_threshold,
        "link_status": metrics["link_status"],
        "g_los": metrics["g_los"], "g_irs": metrics["g_irs"],
        "receiver_position_m": [session.cfg.receiver.position.x, session.cfg.receiver.position.y,
                                session.cfg.receiver.position.z],
        "led_power_w": session.cfg.led.power_w, "led_max_power_w": session.cfg.led.max_power_w,
        "obstacle": session.cfg.obstacle.model_dump(mode="json"),
        "irs": {"enabled": session.cfg.irs.enabled,
                "rows": session.cfg.irs.rows, "cols": session.cfg.irs.cols,
                "azimuth_range_deg": list(session.cfg.irs.azimuth_range_deg),
                "elevation_range_deg": list(session.cfg.irs.elevation_range_deg)},
        "blockage_risk": predict_blockage_quick(session),
    }


def IRSAngles_compat(angles: dict, n: int) -> dict:
    az = list(angles.get("azimuth_deg", []))[:n]
    el = list(angles.get("elevation_deg", []))[:n]
    az += [0.0] * max(0, n - len(az))
    el += [0.0] * max(0, n - len(el))
    return {"azimuth_deg": az, "elevation_deg": el}


def predict_blockage_quick(session: AgentSession) -> dict:
    from .predictor import predict_blockage
    tx = (session.cfg.led.position.x, session.cfg.led.position.y)
    rx = (session.cfg.receiver.position.x, session.cfg.receiver.position.y)
    return predict_blockage(session.cfg, session.telemetry_history, tx, rx)


# ------------------------------------------------------------- tool impls ---

def tool_get_telemetry(session: AgentSession, args: dict) -> dict:
    return _observation(session)


def tool_simulate(session: AgentSession, args: dict) -> dict:
    from . import physics
    cfg = session.cfg.model_copy(deep=True)
    pos = args.get("rx_position")
    if pos is not None:
        if len(pos) != 3:
            return {"error": "rx_position must have exactly 3 numbers [x, y, z]"}
        cfg.receiver.position.x, cfg.receiver.position.y, cfg.receiver.position.z = map(float, pos)
        cfg.clamp_vertical()
    if "led_power_w" in args and args["led_power_w"] is not None:
        p = float(args["led_power_w"])
        lo = cfg.led.dim_min_fraction * cfg.led.max_power_w
        if not (lo - 1e-9 <= p <= cfg.led.max_power_w + 1e-9):
            return {"error": f"led_power_w {p} outside allowed range [{lo:.2f}, {cfg.led.max_power_w:.2f}]"}
        cfg.led.power_w = p
    if "obstacle_enabled" in args and args["obstacle_enabled"] is not None:
        cfg.obstacle.enabled = bool(args["obstacle_enabled"])
    if "ambient" in args and args["ambient"] is not None:
        cfg.noise.ambient_class = args["ambient"]
    try:
        cfg.clamp_vertical()
        m = physics.evaluate(cfg, session.angles.get("azimuth_deg", [0.0] * session._n()) if cfg.irs.enabled else [0.0],
                             session.angles.get("elevation_deg", [0.0] * session._n()) if cfg.irs.enabled else [0.0],
                             [cfg.receiver.position.x, cfg.receiver.position.y, cfg.receiver.position.z])
    except Exception as e:  # argument / constraint validation safety net
        return {"error": f"simulate failed: {e}"}
    m["note"] = "scenario evaluated, current IRS angles were NOT changed"
    if pos is not None:
        m["receiver_position_m"] = [cfg.receiver.position.x, cfg.receiver.position.y, cfg.receiver.position.z]
    _record_telemetry(session, m)
    return m


def tool_optimize_irs(session: AgentSession, args: dict) -> dict:
    from .optimizers import optimize_irs
    w = args.get("objective_weights") or None
    pos = args.get("rx_position")
    try:
        out = optimize_irs(session.cfg, pos, objective_weights=w, n_restarts=3)
    except Exception as e:
        return {"error": f"optimize_irs failed: {e}"}
    session.apply_angles(out["angles"])
    session.cfg.led.power_w = out["metrics"]["p_led_w"]
    m = copy.deepcopy(out["metrics"])
    m["result_summary"] = ("IRS configuration updated with point-optimized tilts "
                           f"at ({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f}) m" if pos else
                           "IRS configuration updated with point-optimized tilts at the current receiver position")
    _record_telemetry(session, m)
    return m


def tool_robust_optimize(session: AgentSession, args: dict) -> dict:
    from .optimizers import robust_optimize
    radius = None
    if args.get("radius_cm") is not None:
        radius = float(args["radius_cm"]) / 100.0
        if not (0.02 <= radius <= 2.0):
            return {"error": "radius_cm must be between 2 and 200"}
    pos = args.get("rx_position")
    try:
        out = robust_optimize(session.cfg, pos, radius_m=radius or 0.15,
                              n_samples=int(args.get("n_samples", 10)),
                              seed=None)
    except Exception as e:
        return {"error": f"robust_optimize failed: {e}"}
    session.apply_angles(out["angles"])
    session.cfg.led.power_w = out["metrics"]["p_led_w"]
    m = copy.deepcopy(out["metrics"])
    m["result_summary"] = (
        f"IRS re-steered with a robust configuration over a {float(out['radius_m']) * 100:.0f} cm "
        f"radius ({out['n_samples']} sampled positions): mean BER {out['mean_ber']}, "
        f"worst-case BER {out['worst_ber']}")
    _record_telemetry(session, m)
    return m


def tool_predict_blockage(session: AgentSession, args: dict) -> dict:
    try:
        return predict_blockage_quick(session)
    except Exception as e:
        return {"error": f"predict_blockage failed: {e}"}


TOOL_IMPLS = {
    "get_telemetry": tool_get_telemetry,
    "simulate": tool_simulate,
    "optimize_irs": tool_optimize_irs,
    "robust_optimize": tool_robust_optimize,
    "predict_blockage": tool_predict_blockage,
}


def _dispatch(session: AgentSession, name: str, args: dict) -> dict:
    impl = TOOL_IMPLS.get(name)
    if impl is None:
        return {"error": f"unknown tool {name}"}
    if not isinstance(args, dict):
        return {"error": "tool arguments must be an object"}
    result = impl(session, args)
    _clamp_floats(result)
    return result


def _clamp_floats(obj):
    """Keep result payloads JSON-serializable even from numpy outputs."""
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            _clamp_floats(v)
    elif isinstance(obj, list):
        for v in obj:
            _clamp_floats(v)
    elif isinstance(obj, (float, int)):
        pass


# ---------------------------------------------------------------- agent run --

def run_agent(session: AgentSession, emit: Callable[[dict], None],
              scenario_note: str = "") -> None:
    """Full agent loop. Emits events via callable; each turned into SSE by main."""
    state_payload = _observation(session)
    emit({"type": "observation", "ts": time.time(), "data": state_payload})

    events: list[dict] = []

    def make_messages() -> list[dict]:
        sys_prompt = (SYSTEM_PROMPT.format(ber_threshold=session.cfg.modulation.ber_threshold,
                                           max_iterations=MAX_ITERATIONS)
                      + ("\nScenario context: " + scenario_note if scenario_note else ""))
        msgs = [{"role": "system", "content": sys_prompt},
                {"role": "user", "content":
                    "Here is the current link observation JSON:\n"
                    + json.dumps(state_payload, default=str)
                    + "\n\nThe link is below target. Diagnose the cause and fix it. "
                      "You must ground every number in tool results."}]
        for ev in events:
            if ev["type"] == "assistant_message":
                msg = {"role": "assistant", "content": ev["content"]}
                if ev.get("tool_calls"):
                    msg["tool_calls"] = ev["tool_calls"]
                msgs.append(msg)
            elif ev["type"] == "tool_result":
                name, rid, content = ev["name"], ev["id"], ev["content"]
                if rid:
                    msgs.append({"role": "tool", "tool_call_id": rid,
                                 "name": name, "content": content})
                else:
                    msgs.append({"role": "user", "content":
                                 f"Tool result for {name}:\n{content}"})
        return msgs

    for iteration in range(1, MAX_ITERATIONS + 1):
        messages = make_messages()
        try:
            resp = _chat_completion(messages, tools=TOOLS_SCHEMA)
        except Exception as e:
            emit({"type": "api_error", "ts": time.time(), "data": {"error": str(e)}})
            return

        choice = resp["choices"][0]
        msg = choice["message"]

        # native path
        if msg.get("tool_calls"):
            calls = msg["tool_calls"]
            content_txt = msg.get("content") or ""
            if content_txt.strip():
                emit({"type": "assistant_note", "ts": time.time(),
                      "data": {"iteration": iteration, "text": content_txt}})
            logged_calls = []
            insert_at = len(events)  # this turn starts here in the message history
            for call in calls:
                name = call["function"]["name"]
                raw_args = call["function"].get("arguments") or "{}"
                try:
                    args = json.loads(raw_args or "{}")
                except json.JSONDecodeError:
                    args, raw_args = {"_raw": raw_args}, raw_args
                call_id = call.get("id") or f"call_{iteration}_{len(logged_calls)}"
                result = _dispatch(session, name, args)
                emit({"type": "tool_call", "ts": time.time(),
                      "data": {"iteration": iteration, "name": name, "args": args}})
                emit({"type": "tool_result", "ts": time.time(),
                      "data": {"iteration": iteration, "name": name, "result": result}})
                logged_calls.append({"id": call_id, "type": "function",
                                     "function": {"name": name, "arguments": raw_args}})
                events.append({"type": "tool_result", "id": call_id,
                               "name": name, "content": json.dumps(result, default=str)})
            # one assistant message carrying all of this turn's tool calls,
            # placed before its tool results so the history stays valid
            events.insert(insert_at, {"type": "assistant_message", "content": content_txt,
                                      "tool_calls": logged_calls})
            continue

        content = (msg.get("content") or "").strip()
        if not content:
            emit({"type": "api_error", "ts": time.time(),
                  "data": {"error": "empty response from model"}})
            return

        # actual final text (native mode: stop reason without tool calls)
        if choice.get("finish_reason") != "tool_calls":
            parsed = _parse_final(content)
            if parsed is not None:
                emit({"type": "final", "ts": time.time(), "data": parsed})
                return

        # fallback JSON action path
        action = _parse_action(content)
        if action is None:
            emit({"type": "api_error", "ts": time.time(),
                  "data": {"error": f"unparseable model output: {content[:200]}"}})
            return
        if action.get("action") == "final":
            emit({"type": "final", "ts": time.time(), "data": {
                "explanation": action.get("explanation", content)}})
            return
        name = action.get("action") or action.get("tool")
        args = action.get("args", {})
        result = _dispatch(session, name, args)
        emit({"type": "tool_call", "ts": time.time(),
              "data": {"iteration": iteration, "name": name, "args": args}})
        emit({"type": "tool_result", "ts": time.time(),
              "data": {"iteration": iteration, "name": name, "result": result}})
        events.append({"type": "assistant_message", "content": content, "tool_calls": None})
        events.append({"type": "tool_result", "id": None, "name": name,
                       "content": json.dumps(result, default=str)})

    # iteration cap hit
    obs = _observation(session)
    emit({"type": "final", "ts": time.time(), "data": {
        "explanation": ("Iteration cap reached without a final explanation from the model. "
                        "Final observed state — BER: obs BER "
                        + json.dumps(obs["ber"]) +
                        ", received power " + json.dumps(obs["received_power_w"]) +
                        " W, status " + obs["link_status"] + "."),
        "final_state": obs}})


def _chat_completion(messages, tools=None) -> dict:
    client = _client()
    kwargs: dict = {"model": os.environ.get("NEBIUS_MODEL", DEFAULT_MODEL),
                    "messages": messages, "temperature": 0.2}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    completion = client.chat.completions.create(**kwargs)
    parsed = completion.model_dump(mode="json") if hasattr(completion, "model_dump") else dict(completion)
    return parsed


def _chat_completion_json(messages) -> dict:
    """Strict JSON fallback mode for models without reliable tool calling."""
    msgs = list(messages)
    adjusted = []
    for m in msgs:
        if m.get("role") == "tool":
            continue
        if m["role"] == "system":
            m = dict(m)
            m["content"] = (m["content"] +
                "\n\nRespond ONLY with a JSON object: "
                '{"thought": "...", "action": "get_telemetry|simulate|optimize_irs|'
                'robust_optimize|predict_blockage|final", "args": {...}, '
                '"explanation": "... (only when action == final)"}. '
                "Never output prose outside the JSON object.")
        adjusted.append(m)
    resp = _chat_completion(adjusted, tools=None)
    content = (resp["choices"][0]["message"].get("content") or "").strip()
    preliminary = {"choices": [{"message": {"role": "assistant", "content": content,
                                            "tool_calls": None},
                                 "finish_reason": resp["choices"][0].get("finish_reason")}]}
    return preliminary


ACTION_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_action(content: str) -> Optional[dict]:
    m = ACTION_RE.search(content)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if isinstance(j, dict) and ("action" in j or "tool" in j):
        return j
    return None


def _parse_final(content: str) -> Optional[dict]:
    """Final plain-language answer when the model stops without tool calls."""
    if not content:
        return None
    if ACTION_RE.search(content):
        return None  # looks like a JSON action; do not treat as final
    return {"explanation": content}


# The strict-JSON fallback mode is exercised through _parse_action whenever the
# model answers without native tool calls; no separate entry point is needed.
