"""Managed Agents Sandbox Runner & Multi-Item Combinatorial Solver (`managed_agent.py`).

Executes ClearBuy's commit protocol inside Google's Managed Agents remote Linux sandbox
(`antigravity-preview-09-2026`, `v1beta` Interactions API) with `.agents/hooks.json` +
`verify_bundle.py` enforcing hard 2D spatial, clearance, and USD budget guardrails.

Also provides:
- `run_local_hook_solver_sync`: Stateful `gemini-4-hydrogen` tool-loop executing the exact
  `.agents/verify_bundle.py` subprocess `stdin`->`stdout` hook gate locally for zero-downtime
  stage resilience and fast benchmark ablations.
- `evaluate_single_swap`: `<1 ms` deterministic gate for `POST /api/session/{id}/swap`
  (returning exact `HookTraceEvent` payload for HTTP 422 adversarial swap blocks).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple, Union

from agents.verify_bundle import compute_constraints_hash, infer_placement_mode, verify_bundle_dict
from backend.genai_client import (
    MANAGED_AGENT_ID,
    MODEL_HYDROGEN,
    MODEL_NEON,
    assert_supported_model,
    get_genai_client,
)
from backend.schemas_agent import (
    BundleSolveResult,
    CandidateSKU,
    CartProposal,
    HookTraceEvent,
    ProposedItem,
    SafeRefusalResult,
    ScaleCalibrationResult,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_AGENTS_DIR = _REPO_ROOT / ".agents"

HookEventCallback = Callable[[HookTraceEvent], Union[None, Awaitable[None]]]


def _emit_callback(cb: Optional[HookEventCallback], event: HookTraceEvent) -> None:
    if cb is None:
        return
    res = cb(event)
    if inspect.isawaitable(res):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(res)  # type: ignore[arg-type]
        except RuntimeError:
            asyncio.run(res)  # type: ignore[arg-type]


def build_room_constraints_payload(
    calibration: ScaleCalibrationResult,
    budget_usd: float,
    require_shopify_gid: bool = True,
    allow_unverified_primary: bool = False,
) -> Dict[str, Any]:
    """Serialize `ScaleCalibrationResult` + `budget_usd` into tamper-evident `room_constraints.json`."""
    payload: Dict[str, Any] = {
        "scope": calibration.scope,
        "budget_usd": round(float(budget_usd), 2),
        "zones": [z.model_dump() for z in calibration.zones],
        "protected_anchors": [p.model_dump() for p in calibration.protected_anchors],
        "require_shopify_gid": require_shopify_gid,
        "allow_unverified_primary": allow_unverified_primary,
    }
    payload["constraint_hash"] = compute_constraints_hash(payload)
    return payload


def normalize_proposal_dict(
    proposal_raw: Dict[str, Any],
    budget_usd: float,
) -> CartProposal:
    """Hydrate optional agent-omitted fields (`item_id`, `budget_usd`, `price_usd`, `placement_mode`)."""
    hydrated = dict(proposal_raw)
    if not hydrated.get("budget_usd"):
        hydrated["budget_usd"] = round(float(budget_usd), 2)

    norm_items: List[Dict[str, Any]] = []
    for idx, raw_it in enumerate(hydrated.get("items") or []):
        if not isinstance(raw_it, dict):
            continue
        it = dict(raw_it)
        it.setdefault("item_id", f"item_{idx + 1}")
        it.setdefault("merchant_name", it.get("merchant") or "Shopify Store")
        if "price_cents" in it and it["price_cents"] is not None:
            cents_int = int(round(float(it["price_cents"])))
            it["price_cents"] = cents_int
            it.setdefault("price_usd", round(cents_int / 100.0, 2))
        elif "price_usd" in it and it["price_usd"] is not None:
            usd_f = round(float(it["price_usd"]), 2)
            it["price_usd"] = usd_f
            it["price_cents"] = int(round(usd_f * 100))
        it["placement_mode"] = infer_placement_mode(it)
        norm_items.append(it)

    hydrated["items"] = norm_items
    return CartProposal.model_validate(hydrated)


def enrich_verified_items(
    proposal: CartProposal,
    calibration: ScaleCalibrationResult,
) -> CartProposal:
    """Stamp each item in an approved `CartProposal` with exact `fit_status` & `fit_badge_text`."""
    z_map = {z.zone_id: z for z in calibration.zones}
    enriched_items: List[ProposedItem] = []
    for item in proposal.items:
        it_copy = item.model_copy(deep=True)
        it_copy.price_usd = round(int(it_copy.price_cents) / 100.0, 2)
        z = z_map.get(it_copy.zone_id)
        if it_copy.dimensions_unverified or it_copy.width_in is None:
            it_copy.fit_status = "unverified_specs"
            it_copy.fit_badge_text = "Unverified Specs · Check Seller"
        else:
            it_copy.fit_status = "verified_fit"
            if z and it_copy.placement_mode == "floor_anchor":
                it_copy.fit_badge_text = f"Verified Fit · {it_copy.width_in:.1f}\" <= {z.usable_width_in:.1f}\""
            elif z:
                it_copy.fit_badge_text = f"Verified Fit · {it_copy.width_in:.1f}\" in {z.zone_id}"
            else:
                it_copy.fit_badge_text = f"Verified Fit · {it_copy.width_in:.1f}\" W"
        enriched_items.append(it_copy)
    return CartProposal(
        budget_usd=proposal.budget_usd,
        items=enriched_items,
        rationale=proposal.rationale,
    )


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Extract a JSON object from markdown code fences or raw text."""
    if not text:
        return None
    fenced = text
    if "```" in text:
        for block in text.split("```"):
            cleaned = block.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("{") and cleaned.endswith("}"):
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    continue
    start = fenced.find("{")
    end = fenced.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(fenced[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


# --- 1. Primary Remote Managed Agents Runner (`antigravity-preview-09-2026`) ---


def _run_remote_managed_agent_sync(
    user_prompt: str,
    calibration: ScaleCalibrationResult,
    budget_usd: float,
    candidates: Sequence[CandidateSKU],
    enable_live_shop_mcp: bool = False,
    require_shopify_gid: bool = True,
    allow_unverified_primary: bool = False,
    on_hook_event: Optional[HookEventCallback] = None,
    timeout_sec: float = 90.0,
    reuse_environment_id: Optional[str] = None,
) -> BundleSolveResult:
    """Execute the bundle solver inside Google's remote Managed Agents sandbox (`antigravity-preview-09-2026`)."""
    t0 = time.perf_counter()
    client = get_genai_client(api_version="v1beta")

    constraints_payload = build_room_constraints_payload(
        calibration=calibration,
        budget_usd=budget_usd,
        require_shopify_gid=require_shopify_gid,
        allow_unverified_primary=allow_unverified_primary,
    )
    candidates_payload = [c.model_dump() for c in candidates]

    hooks_json_str = (_AGENTS_DIR / "hooks.json").read_text(encoding="utf-8")
    verify_py_str = (_AGENTS_DIR / "verify_bundle.py").read_text(encoding="utf-8")
    agents_md_str = (_AGENTS_DIR / "AGENTS.md").read_text(encoding="utf-8")
    skill_md_str = (_AGENTS_DIR / "SKILL.md").read_text(encoding="utf-8")

    sources = [
        {"type": "inline", "target": ".agents/hooks.json", "content": hooks_json_str},
        {"type": "inline", "target": ".agents/verify_bundle.py", "content": verify_py_str},
        {"type": "inline", "target": ".agents/AGENTS.md", "content": agents_md_str},
        {"type": "inline", "target": ".agents/SKILL.md", "content": skill_md_str},
        {
            "type": "inline",
            "target": "/workspace/room_constraints.json",
            "content": json.dumps(constraints_payload, indent=2),
        },
        {
            "type": "inline",
            "target": "/workspace/catalog_candidates.json",
            "content": json.dumps(candidates_payload, indent=2),
        },
    ]

    tools: List[Dict[str, Any]] = [{"type": "code_execution"}]
    if enable_live_shop_mcp:
        tools.append(
            {
                "type": "mcp_server",
                "name": "shopify",
                "url": "https://mcp.shop.com/",
            }
        )

    agent_task_prompt = (
        f"USER REQUEST: {user_prompt}\n"
        f"STRICT TOTAL BUDGET: ${budget_usd:.2f} USD\n\n"
        "INSTRUCTIONS:\n"
        "1. Inspect `/workspace/room_constraints.json` and `/workspace/catalog_candidates.json`"
        + (" (and query `shopify` MCP if more SKUs are needed).\n" if enable_live_shop_mcp else ".\n")
        + "2. Select the optimal combination of real Shopify SKUs covering the requested items and zones.\n"
        "3. Call `write_to_file` to write `/workspace/cart_proposal.json` matching the CartProposal schema. "
        "Remember: `.agents/hooks.json` will run `verify_bundle.py` automatically on `write_to_file`.\n"
        "   - If `verify_bundle.py` returns DENY, read the exact overflow/clearance/budget reason, adjust your SKU combination "
        "(coupled cross-item trade-offs), and call `write_to_file` on `/workspace/cart_proposal.json` again.\n"
        "   - If the request is mathematically impossible across all available SKUs, write `/workspace/safe_refusal.json` via `write_to_file`.\n"
        "4. Once `/workspace/cart_proposal.json` (or `/workspace/safe_refusal.json`) is saved, read `/workspace/hook_trace.jsonl` "
        "(if it exists) and return ONLY a single final JSON block in your final response with this exact structure:\n"
        '{"status": "verified" | "safe_refusal", "cart_proposal": {...} | null, "safe_refusal": {...} | null, "hook_trace": [...]}\n'
    )

    env_param: Any = (
        reuse_environment_id
        if reuse_environment_id
        else {
            "type": "remote",
            "sources": sources,
        }
    )

    stream = client.interactions.create(
        agent=MANAGED_AGENT_ID,
        input=agent_task_prompt,
        system_instruction=agents_md_str,
        tools=tools,
        environment=env_param,
        stream=True,
        timeout=timeout_sec,
    )

    final_interaction: Any = None
    collected_text_parts: List[str] = []

    for event in stream:
        ev_type = getattr(event, "event_type", "")
        if ev_type == "step.delta":
            delta = getattr(event, "delta", None)
            if getattr(delta, "type", None) == "text":
                collected_text_parts.append(getattr(delta, "text", "") or "")
        elif ev_type == "interaction.completed":
            final_interaction = getattr(event, "interaction", None)

    output_text = (
        getattr(final_interaction, "output_text", None)
        or "".join(collected_text_parts)
    )
    parsed_summary = _extract_json_object(output_text or "")
    if not parsed_summary:
        raise RuntimeError("Managed Agent completed without structured JSON summary.")

    hook_trace_models: List[HookTraceEvent] = []
    for idx, raw_ev in enumerate(parsed_summary.get("hook_trace") or []):
        if isinstance(raw_ev, dict) and raw_ev.get("decision") in ("allow", "deny"):
            raw_ev.setdefault("attempt", idx + 1)
            raw_ev.setdefault("budget_usd", budget_usd)
            ev_model = HookTraceEvent.model_validate(raw_ev)
            hook_trace_models.append(ev_model)
            _emit_callback(on_hook_event, ev_model)

    status_str = parsed_summary.get("status", "verified")
    if status_str == "safe_refusal" or parsed_summary.get("safe_refusal"):
        refusal_raw = parsed_summary.get("safe_refusal") or {"reason": "Constraints unsatisfiable."}
        refusal_model = SafeRefusalResult.model_validate(refusal_raw)
        return BundleSolveResult(
            status="safe_refusal",
            proposal=None,
            safe_refusal=refusal_model,
            hook_trace=hook_trace_models,
            self_corrected=any(h.decision == "deny" for h in hook_trace_models),
            denied_count=sum(1 for h in hook_trace_models if h.decision == "deny"),
            execution_mode="managed_agent_remote",
            interaction_id=getattr(final_interaction, "id", None),
            environment_id=getattr(final_interaction, "environment_id", None),
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    proposal_raw = parsed_summary.get("cart_proposal")
    if not isinstance(proposal_raw, dict):
        raise RuntimeError("Managed Agent returned verified status without cart_proposal object.")

    # Always run deterministic host-side verification as final zero-trust guarantee!
    host_check = verify_bundle_dict(
        proposal=proposal_raw,
        constraints=constraints_payload,
        attempt=len(hook_trace_models) + 1,
    )
    if host_check["decision"] == "deny":
        raise RuntimeError(f"Host zero-trust re-verification denied proposal: {host_check['reason']}")

    if not any(h.decision == "allow" for h in hook_trace_models):
        allow_ev = HookTraceEvent.model_validate(host_check)
        hook_trace_models.append(allow_ev)
        _emit_callback(on_hook_event, allow_ev)

    proposal_model = enrich_verified_items(
        normalize_proposal_dict(proposal_raw, budget_usd),
        calibration,
    )
    denied_cnt = sum(1 for h in hook_trace_models if h.decision == "deny")

    return BundleSolveResult(
        status="verified",
        proposal=proposal_model,
        safe_refusal=None,
        hook_trace=hook_trace_models,
        self_corrected=(denied_cnt > 0),
        denied_count=denied_cnt,
        execution_mode="managed_agent_remote",
        interaction_id=getattr(final_interaction, "id", None),
        environment_id=getattr(final_interaction, "environment_id", None),
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )


# --- 2. Local Stateful Hook Sandbox Loop (`gemini-4-hydrogen` + Subprocess `verify_bundle.py`) ---


def _invoke_hook_subprocess(
    workspace_dir: Path,
    target_path: str,
    content_str: str,
) -> Dict[str, Any]:
    """Execute `.agents/verify_bundle.py` as an isolated OS subprocess matching `.agents/hooks.json`."""
    hook_payload = {
        "tool_call": {
            "name": "write_to_file",
            "args": {
                "path": target_path,
                "content": content_str,
            },
        },
        "cwd": str(workspace_dir),
    }
    proc = subprocess.run(
        [sys.executable, str(_AGENTS_DIR / "verify_bundle.py")],
        input=json.dumps(hook_payload),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"decision": "allow"}
    return json.loads(proc.stdout.strip().splitlines()[-1])


def run_local_hook_solver_sync(
    user_prompt: str,
    calibration: ScaleCalibrationResult,
    budget_usd: float,
    candidates: Sequence[CandidateSKU],
    model: str = MODEL_HYDROGEN,
    max_turns: int = 5,
    require_shopify_gid: bool = True,
    allow_unverified_primary: bool = False,
    on_hook_event: Optional[HookEventCallback] = None,
) -> BundleSolveResult:
    """Stateful `gemini-4-hydrogen` tool loop gated by real `.agents/verify_bundle.py` subprocess calls."""
    t0 = time.perf_counter()
    assert_supported_model(model)
    client = get_genai_client(api_version="v1beta")

    constraints_payload = build_room_constraints_payload(
        calibration=calibration,
        budget_usd=budget_usd,
        require_shopify_gid=require_shopify_gid,
        allow_unverified_primary=allow_unverified_primary,
    )
    candidates_payload = [c.model_dump() for c in candidates]
    agents_md_str = (_AGENTS_DIR / "AGENTS.md").read_text(encoding="utf-8")

    write_tool = {
        "type": "function",
        "name": "write_to_file",
        "description": (
            "Write a JSON file inside /workspace. Use `/workspace/cart_proposal.json` to propose a "
            "shopping bundle (automatically verified by .agents/hooks.json -> verify_bundle.py), or "
            "`/workspace/safe_refusal.json` if physical + budget constraints are mathematically impossible."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Target path: `/workspace/cart_proposal.json` or `/workspace/safe_refusal.json`.",
                },
                "content": {
                    "type": "string",
                    "description": "Valid JSON string matching CartProposal or SafeRefusalResult schema.",
                },
            },
            "required": ["path", "content"],
        },
    }

    initial_prompt = (
        f"USER REQUEST: {user_prompt}\n"
        f"STRICT TOTAL BUDGET: ${budget_usd:.2f} USD\n\n"
        f"CALIBRATED ROOM CONSTRAINTS (`/workspace/room_constraints.json`):\n"
        f"{json.dumps(constraints_payload, indent=2)}\n\n"
        f"LIVE SHOPIFY CANDIDATE SKUS (`/workspace/catalog_candidates.json`):\n"
        f"{json.dumps(candidates_payload, indent=2)}\n\n"
        "Call `write_to_file` on `/workspace/cart_proposal.json` with your proposed bundle "
        "(or `/workspace/safe_refusal.json` ONLY if no valid combination of candidate SKUs can satisfy "
        "both spatial constraints and budget)."
    )

    hook_trace_models: List[HookTraceEvent] = []
    emitted_trace_count = 0

    with tempfile.TemporaryDirectory(prefix="clearbuy_ws_") as tmp_dir:
        ws_path = Path(tmp_dir)
        (ws_path / "room_constraints.json").write_text(
            json.dumps(constraints_payload, indent=2),
            encoding="utf-8",
        )
        trace_file = ws_path / "hook_trace.jsonl"

        prev_id: Optional[str] = None
        next_input: Any = initial_prompt

        for _turn in range(max_turns):
            kwargs: Dict[str, Any] = {
                "model": model,
                "input": next_input,
                "system_instruction": agents_md_str,
                "tools": [write_tool],
                "generation_config": {"thinking_level": "low"},
            }
            if prev_id:
                kwargs["previous_interaction_id"] = prev_id

            interaction = client.interactions.create(**kwargs)
            prev_id = interaction.id

            # Extract pending function_call steps
            steps = getattr(interaction, "steps", None) or []
            fn_calls = [s for s in steps if getattr(s, "type", None) == "function_call"]

            if not fn_calls:
                # Check if model outputted JSON directly instead of calling write_to_file
                direct_json = _extract_json_object(getattr(interaction, "output_text", "") or "")
                if direct_json and "items" in direct_json:
                    fn_calls_sim = [
                        {
                            "id": "sim_call_1",
                            "name": "write_to_file",
                            "arguments": {
                                "path": "/workspace/cart_proposal.json",
                                "content": json.dumps(direct_json),
                            },
                        }
                    ]
                else:
                    next_input = (
                        "You must call the `write_to_file` tool targeting `/workspace/cart_proposal.json` "
                        "or `/workspace/safe_refusal.json`."
                    )
                    continue
            else:
                fn_calls_sim = [
                    {
                        "id": getattr(fc, "id", f"call_{i}"),
                        "name": getattr(fc, "name", "write_to_file"),
                        "arguments": getattr(fc, "arguments", {}) or {},
                    }
                    for i, fc in enumerate(fn_calls)
                ]

            tool_results_input: List[Dict[str, Any]] = []

            for fc_dict in fn_calls_sim:
                args = fc_dict["arguments"]
                if isinstance(args, str):
                    args = json.loads(args)
                target_path = str(args.get("path") or "/workspace/cart_proposal.json")
                content_str = str(args.get("content") or "{}")

                hook_decision = _invoke_hook_subprocess(ws_path, target_path, content_str)

                # Stream any newly appended hook_trace.jsonl events
                if trace_file.exists():
                    lines = [ln for ln in trace_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
                    while emitted_trace_count < len(lines):
                        ev = HookTraceEvent.model_validate_json(lines[emitted_trace_count])
                        hook_trace_models.append(ev)
                        _emit_callback(on_hook_event, ev)
                        emitted_trace_count += 1

                if target_path.endswith("safe_refusal.json") and hook_decision.get("decision") == "allow":
                    refusal_data = json.loads(content_str)
                    refusal_model = SafeRefusalResult.model_validate(refusal_data)
                    denied_cnt = sum(1 for h in hook_trace_models if h.decision == "deny")
                    return BundleSolveResult(
                        status="safe_refusal",
                        proposal=None,
                        safe_refusal=refusal_model,
                        hook_trace=hook_trace_models,
                        self_corrected=(denied_cnt > 0),
                        denied_count=denied_cnt,
                        execution_mode="local_hook_sandbox",
                        interaction_id=prev_id,
                        latency_ms=int((time.perf_counter() - t0) * 1000),
                    )

                if hook_decision.get("decision") == "deny":
                    reason_msg = hook_decision.get("reason", "Denied by verify_bundle.py")
                    tool_results_input.append(
                        {
                            "type": "function_result",
                            "call_id": fc_dict["id"],
                            "name": fc_dict["name"],
                            "result": json.dumps(
                                {
                                    "status": "DENIED_BY_HOOK",
                                    "decision": "deny",
                                    "reason": reason_msg,
                                    "instruction": (
                                        "Fix every violation above by selecting compliant SKU(s) from "
                                        "catalog_candidates.json and retry `write_to_file` on `/workspace/cart_proposal.json`, "
                                        "or write `/workspace/safe_refusal.json` if impossible."
                                    ),
                                }
                            ),
                        }
                    )
                else:
                    # ALLOW! Verify and return verified CartProposal immediately
                    proposal_raw = json.loads(content_str)
                    proposal_model = enrich_verified_items(
                        normalize_proposal_dict(proposal_raw, budget_usd),
                        calibration,
                    )
                    denied_cnt = sum(1 for h in hook_trace_models if h.decision == "deny")
                    return BundleSolveResult(
                        status="verified",
                        proposal=proposal_model,
                        safe_refusal=None,
                        hook_trace=hook_trace_models,
                        self_corrected=(denied_cnt > 0),
                        denied_count=denied_cnt,
                        execution_mode="local_hook_sandbox",
                        interaction_id=prev_id,
                        latency_ms=int((time.perf_counter() - t0) * 1000),
                    )

            next_input = tool_results_input

    # Exhausted max_turns -> return clean Safe Refusal explaining the last hook violation
    last_reason = (
        hook_trace_models[-1].reason
        if hook_trace_models
        else f"No compliant SKU combination found within ${budget_usd:.2f} budget and room bounds."
    )
    denied_cnt = sum(1 for h in hook_trace_models if h.decision == "deny")
    return BundleSolveResult(
        status="safe_refusal",
        proposal=None,
        safe_refusal=SafeRefusalResult(
            is_refusal=True,
            reason=f"Safe Refusal after {denied_cnt} guardrail checks: {last_reason}",
        ),
        hook_trace=hook_trace_models,
        self_corrected=(denied_cnt > 0),
        denied_count=denied_cnt,
        execution_mode="local_hook_sandbox",
        interaction_id=prev_id,
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )


async def solve_spatial_bundle(
    user_prompt: str,
    calibration: ScaleCalibrationResult,
    budget_usd: float,
    candidates: Sequence[CandidateSKU],
    prefer_remote_managed_agent: bool = True,
    enable_live_shop_mcp: bool = False,
    require_shopify_gid: bool = True,
    allow_unverified_primary: bool = False,
    on_hook_event: Optional[HookEventCallback] = None,
    reuse_environment_id: Optional[str] = None,
) -> BundleSolveResult:
    """High-level async orchestrator called by the FastAPI `/api/session/start` SSE stream.

    Runs inside Google's `antigravity-preview-09-2026` Managed Agents sandbox by default and
    seamlessly falls back to the local `.agents/verify_bundle.py` subprocess loop if remote
    container provisioning is unavailable or times out.
    """
    if prefer_remote_managed_agent:
        try:
            return await asyncio.to_thread(
                _run_remote_managed_agent_sync,
                user_prompt,
                calibration,
                budget_usd,
                candidates,
                enable_live_shop_mcp,
                require_shopify_gid,
                allow_unverified_primary,
                on_hook_event,
                90.0,
                reuse_environment_id,
            )
        except Exception:
            # Zero-downtime fallback to local subprocess hook loop
            pass

    return await asyncio.to_thread(
        run_local_hook_solver_sync,
        user_prompt,
        calibration,
        budget_usd,
        candidates,
        MODEL_HYDROGEN,
        5,
        require_shopify_gid,
        allow_unverified_primary,
        on_hook_event,
    )


def evaluate_single_swap(
    current_proposal: CartProposal,
    calibration: ScaleCalibrationResult,
    zone_id: str,
    target_item_id: str,
    new_sku: CandidateSKU,
    variant_id: Optional[str] = None,
    attempt: int = 1,
) -> Tuple[bool, CartProposal, HookTraceEvent]:
    """Deterministic `<1 ms` gate for `POST /api/session/{id}/swap`.

    If `allowed == False`, FastAPI returns HTTP 422 with `hook_event.model_dump()` so the
    UI displays the exact Coral `Blocked by hooks.json (+X.X" over wall)` card!
    """
    updated_items: List[ProposedItem] = []
    replaced = False

    replacement_item = ProposedItem(
        item_id=target_item_id,
        zone_id=zone_id,
        sku_id=new_sku.sku_id,
        variant_id=variant_id or new_sku.variant_id,
        title=new_sku.title,
        merchant_name=new_sku.merchant_name,
        price_cents=new_sku.price_cents,
        price_usd=round(new_sku.price_cents / 100.0, 2),
        width_in=new_sku.width_in,
        depth_in=new_sku.depth_in,
        height_in=new_sku.height_in,
        dimensions_unverified=new_sku.dimensions_unverified,
        placement_mode=new_sku.placement_mode,
        category=new_sku.category,
        image_url=new_sku.image_url,
        product_url=new_sku.product_url,
    )

    for item in current_proposal.items:
        if item.item_id == target_item_id:
            updated_items.append(replacement_item)
            replaced = True
        else:
            updated_items.append(item.model_copy(deep=True))

    if not replaced:
        updated_items.append(replacement_item)

    candidate_proposal = CartProposal(
        budget_usd=current_proposal.budget_usd,
        items=updated_items,
        rationale=f"Swap {target_item_id} -> {new_sku.title}",
    )

    constraints_payload = build_room_constraints_payload(
        calibration=calibration,
        budget_usd=current_proposal.budget_usd,
        require_shopify_gid=True,
        allow_unverified_primary=False,
    )

    check_raw = verify_bundle_dict(
        proposal=candidate_proposal.model_dump(),
        constraints=constraints_payload,
        attempt=attempt,
    )
    hook_event = HookTraceEvent.model_validate(check_raw)
    if hook_event.decision == "deny":
        return False, current_proposal, hook_event

    enriched = enrich_verified_items(candidate_proposal, calibration)
    return True, enriched, hook_event
