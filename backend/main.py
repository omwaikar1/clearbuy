"""ClearBuy — FastAPI SSE Orchestrator.

Implements all 5 Frozen API Contracts (Blueprint Section 04, Page 17):
1. `POST /api/session/start` -> SSE stream (`scale_ready`, `catalog_ready`,
   `hook_event`, `cart_ready`, `render_ready`) + `GET /api/session/{id}/stream`
2. `POST /api/session/{id}/thread` -> Conversational voice/text spatial thread
3. `POST /api/session/{id}/swap` -> `verify_bundle` gate (422 on deny) + stateful
   Nano Banana 2.1 surgical swap + `gemini-decision-1` QA + UCP `update_checkout`
4. `PATCH /api/session/{id}/zone` -> Instantaneous CAD measure drag override
5. `GET /api/benchmark` -> 14-room NYU Depth V2 Kinect + Gemini 4 ablation results
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
import uuid
from io import BytesIO
from typing import Any, AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from backend.adapters import (
    annotate_item_fit_badges,
    build_sku_tabs_and_alternatives,
    extract_requested_categories,
    run_scale_calibration,
    solve_combinatorial_bundle,
    solve_combinatorial_bundle_async,
    update_zone_footprints,
    verify_bundle_deterministic,
)
from backend.config import (
    EVAL_DATA_DIR,
    EVAL_RESULTS_PATH,
    get_model_decision,
    get_model_hydrogen,
    get_model_nano_banana,
    get_model_neon,
    get_shop_mcp_url,
    has_live_gemini_credentials,
)
from backend.renderer import (
    compute_hotspot_pins,
    render_initial_bundle,
    render_surgical_swap,
    render_targeted_repair,
)
from backend.schemas import (
    CartReadyEvent,
    CatalogReadyEvent,
    CheckoutCompleteRequest,
    CheckoutCompleteResponse,
    CheckoutPrepareRequest,
    CheckoutPrepareResponse,
    MCPCallTrace,
    MerchantUCPCheckout,
    RenderReadyEvent,
    RenderVersion,
    ShopifySKU,
    SpaceScope,
    SwapRequest,
    SwapResponse,
    ThreadRequest,
    ThreadResponse,
    ZoneOverrideRequest,
    ZoneOverrideResponse,
)
from backend.session_store import SpatialSession, get_session, put_session
from backend.shop_mcp import ShopMCPClient, extract_dimensions_via_hydrogen
from backend.thread_router import handle_thread_utterance
from backend.visual_qa import audit_rendered_room, screen_catalog_candidates

app = FastAPI(
    title="ClearBuy — Verified Spatial Commerce Compiler API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Session-Id"],
)

EVAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/benchmark/assets", StaticFiles(directory=str(EVAL_DATA_DIR)), name="benchmark_assets")


def _sse_frame(event_name: str, data: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(data)}\n\n"


def _normalize_image_bytes(raw_bytes: bytes) -> tuple[bytes, str]:
    """Ensure uploaded room image is clean RGB JPEG <= 1024px on the long edge."""
    img = Image.open(BytesIO(raw_bytes)).convert("RGB")
    if max(img.size) > 1024:
        img.thumbnail((1024, 1024))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue(), "image/jpeg"


async def _run_session_pipeline(session: SpatialSession) -> None:
    """Execute the full 5-stage verified pipeline while emitting live SSE frames."""
    try:
        session.emit_sse(
            "session_started",
            {
                "session_id": session.session_id,
                "prompt": session.prompt,
                "budget_usd": session.budget_usd,
                "scope": session.scope,
            },
        )

        primary_img_bytes, primary_mime = session.room_images[0]

        # ------------------------------------------------------------------
        # Stage 1: Zero-Measurement Scale Calibration across ALL 1-3 uploaded angles (`scale_ready`)
        # ------------------------------------------------------------------
        scale_tasks = [
            run_scale_calibration(
                session_id=session.session_id,
                image_bytes=img_b,
                mime_type=img_m,
                prompt=session.prompt,
                scope=session.scope,
                exif_focal_mm=session.exif_focal_mm,
                thinking_level=os.getenv("CLEARBUY_SCALE_THINKING_LEVEL", "low"),
            )
            for img_b, img_m in session.room_images[:3]
        ]
        angle_scales = await asyncio.gather(*scale_tasks)
        scale_ev = angle_scales[0]
        if len(angle_scales) > 1:
            merged_zones = list(scale_ev.zones)
            merged_anchors = list(scale_ev.anchors_detected)
            merged_protected = list(scale_ev.protected_anchors)
            for a_idx, extra_sc in enumerate(angle_scales[1:], start=2):
                for z in extra_sc.zones:
                    zc = z.model_copy(deep=True)
                    zc.zone_id = f"A{a_idx}_{zc.zone_id}"
                    zc.label = f"Angle {a_idx} · {zc.label}"
                    merged_zones.append(zc)
                merged_anchors.extend(extra_sc.anchors_detected)
                merged_protected.extend(extra_sc.protected_anchors)
            scale_ev.zones = merged_zones
            scale_ev.anchors_detected = merged_anchors
            scale_ev.protected_anchors = merged_protected
            scale_ev.calibration_summary = (
                f"{scale_ev.calibration_summary} · {len(angle_scales)} angles calibrated"
            )
        session.scale = scale_ev
        session.emit_sse("scale_ready", scale_ev.model_dump())

        # ------------------------------------------------------------------
        # Stage 2: Live Shopify `mcp.shop.com` Discovery + Decisions Gate (`catalog_ready`)
        # ------------------------------------------------------------------
        t_cat = time.perf_counter()
        requested_categories = extract_requested_categories(
            session.prompt, scope=scale_ev.detected_scope
        )
        mcp = ShopMCPClient()

        search_tasks = [
            mcp.search_category(
                category=cat,
                style_hint="",
                max_price_usd=session.budget_usd,
                limit=8,
            )
            for cat in requested_categories
        ]
        raw_search_results = await asyncio.gather(*search_tasks)

        candidates_by_category: dict[str, list[ShopifySKU]] = {}
        mcp_traces: list[MCPCallTrace] = []
        stores_seen: set[str] = set()
        total_decisions_ms = 0

        for cat, (skus, trace) in zip(requested_categories, raw_search_results):
            mcp_traces.append(trace)
            for s in skus:
                stores_seen.add(s.shop_domain)
            # Extract structured W x D x H via `gemini-4-hydrogen` + screen via `gemini-decision-1`
            with_dims = await extract_dimensions_via_hydrogen(skus)
            screened, dec_ms = await screen_catalog_candidates(
                prompt=session.prompt,
                category=cat,
                candidates=with_dims,
            )
            total_decisions_ms = max(total_decisions_ms, dec_ms)
            candidates_by_category[cat] = annotate_item_fit_badges(scale_ev.zones, screened)

        session.candidates_by_category = candidates_by_category
        session.mcp_calls.extend(mcp_traces)

        catalog_ev = CatalogReadyEvent(
            session_id=session.session_id,
            queries_executed=requested_categories,
            stores_scanned=len(stores_seen),
            candidates_count=sum(len(v) for v in candidates_by_category.values()),
            mcp_calls=mcp_traces,
            candidates_by_category=candidates_by_category,
            decisions_gate_latency_ms=total_decisions_ms,
            elapsed_ms=int((time.perf_counter() - t_cat) * 1000),
        )
        session.catalog = catalog_ev
        session.emit_sse("catalog_ready", catalog_ev.model_dump())

        # ------------------------------------------------------------------
        # Stage 3: `hooks.json` Combinatorial Solver (`hook_event` DENY -> ALLOW)
        # ------------------------------------------------------------------
        verified_bundle, hook_events, refusal_reason = await solve_combinatorial_bundle_async(
            session_id=session.session_id,
            prompt=session.prompt,
            zones=scale_ev.zones,
            candidates_by_category=candidates_by_category,
            budget_usd=session.budget_usd,
        )
        session.hook_events.extend(hook_events)
        for hev in hook_events:
            session.emit_sse("hook_event", hev.model_dump())

        if refusal_reason or not verified_bundle:
            refusal_cart = CartReadyEvent(
                session_id=session.session_id,
                status="safe_refusal",
                refusal_reason=refusal_reason or "No compliant bundle fits constraints.",
                verified_items=[],
                zones=scale_ev.zones,
                total_cents=0,
                total_usd=0.0,
                budget_usd=session.budget_usd,
                remaining_budget_usd=session.budget_usd,
                checkouts=[],
                mcp_calls=mcp_traces,
            )
            session.cart = refusal_cart
            session.emit_sse("cart_ready", refusal_cart.model_dump())
            session.mark_complete()
            return

        # ------------------------------------------------------------------
        # Stage 4: Live `get_product` Swatches + Per-Merchant UCP Checkouts (`cart_ready`)
        # ------------------------------------------------------------------
        t_cart = time.perf_counter()
        enrich_results = await asyncio.gather(
            *[mcp.enrich_product_variants(it) for it in verified_bundle]
        )
        enriched_items = annotate_item_fit_badges(
            scale_ev.zones, [r[0] for r in enrich_results]
        )
        variant_traces = [r[1] for r in enrich_results]
        session.mcp_calls.extend(variant_traces)

        # Re-verify exact price after live variant enrichment
        post_enrich_hook = verify_bundle_deterministic(
            session_id=session.session_id,
            zones=scale_ev.zones,
            proposed_items=enriched_items,
            budget_usd=session.budget_usd,
            attempt=len(session.hook_events) + 1,
        )
        if post_enrich_hook.decision == "deny":
            # Keep original search variant snapshot if enriched default variant jumped in price
            enriched_items = verified_bundle

        scale_ev.zones = update_zone_footprints(scale_ev.zones, enriched_items)
        sku_tabs, alts_by_sku = build_sku_tabs_and_alternatives(
            session_id=session.session_id,
            zones=scale_ev.zones,
            verified_items=enriched_items,
            candidates_by_category=candidates_by_category,
            budget_usd=session.budget_usd,
        )

        checkouts, ucp_traces = await mcp.create_or_update_merchant_checkouts(enriched_items)
        session.mcp_calls.extend(ucp_traces)
        session.verified_items = enriched_items
        session.sku_tabs = sku_tabs
        session.alternatives_by_sku = alts_by_sku
        session.checkouts = checkouts

        total_cents = sum(it.price_cents for it in enriched_items)
        total_usd = round(total_cents / 100.0, 2)
        cart_ev = CartReadyEvent(
            session_id=session.session_id,
            status="verified",
            verified_items=enriched_items,
            sku_tabs=sku_tabs,
            alternatives_by_sku=alts_by_sku,
            zones=scale_ev.zones,
            total_cents=total_cents,
            total_usd=total_usd,
            budget_usd=session.budget_usd,
            remaining_budget_usd=round(session.budget_usd - total_usd, 2),
            checkouts=checkouts,
            mcp_calls=variant_traces + ucp_traces,
            elapsed_ms=int((time.perf_counter() - t_cart) * 1000),
        )
        session.cart = cart_ev
        session.emit_sse("cart_ready", cart_ev.model_dump())

        # ------------------------------------------------------------------
        # Stage 5: Nano Banana 2.1 Render + `gemini-decision-1` QA (`render_ready`)
        # ------------------------------------------------------------------
        t_ren = time.perf_counter()
        render_bytes, render_mime, inter_id, sku_refs = await render_initial_bundle(
            room_image_bytes=primary_img_bytes,
            room_mime=primary_mime,
            zones=scale_ev.zones,
            verified_items=enriched_items,
            protected_anchors=scale_ev.protected_anchors,
        )

        qa_verdict = await audit_rendered_room(
            original_room_bytes=primary_img_bytes,
            original_mime=primary_mime,
            sku_images=sku_refs,
            rendered_room_bytes=render_bytes,
            rendered_mime=render_mime,
            was_repaired=False,
        )

        repaired = False
        repair_reason: str | None = None
        if qa_verdict.status == "failed" and qa_verdict.defect_summary:
            repair_reason = qa_verdict.defect_summary
            session.emit_sse(
                "qa_repairing",
                {
                    "session_id": session.session_id,
                    "defect_summary": repair_reason,
                    "message": f"Repairing render ({repair_reason})...",
                },
            )
            render_bytes, render_mime, inter_id = await render_targeted_repair(
                room_image_bytes=primary_img_bytes,
                failed_render_bytes=render_bytes,
                prior_interaction_id=inter_id,
                defect_summary=repair_reason,
            )
            repaired = True
            qa_verdict = await audit_rendered_room(
                original_room_bytes=primary_img_bytes,
                original_mime=primary_mime,
                sku_images=sku_refs,
                rendered_room_bytes=render_bytes,
                rendered_mime=render_mime,
                was_repaired=True,
            )

        b64_render = base64.b64encode(render_bytes).decode("utf-8")
        v1 = RenderVersion(
            version_id="v1",
            label="v1 · Initial Verified Layout",
            image_b64=b64_render,
            image_mime=render_mime,
            interaction_id=inter_id,
            decisions_qa=qa_verdict,
            repaired=repaired,
            active_sku_ids=[it.sku_id for it in enriched_items],
        )
        session.versions.append(v1)
        session.last_render_interaction_id = inter_id
        session.last_render_bytes = render_bytes

        pins = compute_hotspot_pins(scale_ev.zones, enriched_items)
        render_ev = RenderReadyEvent(
            session_id=session.session_id,
            version_id="v1",
            versions_available=["v1"],
            image_b64=b64_render,
            image_mime=render_mime,
            hotspot_pins=pins,
            decisions_qa=qa_verdict,
            repaired=repaired,
            repair_reason=repair_reason,
            elapsed_ms=int((time.perf_counter() - t_ren) * 1000),
        )
        session.emit_sse("render_ready", render_ev.model_dump())

        # Speculatively pre-warm top compliant alternatives in parallel so 1-click swaps are <150ms instant!
        if has_live_gemini_credentials() and os.getenv("CLEARBUY_PREWARM_SWAPS", "1") == "1":
            asyncio.create_task(_prewarm_top_alternatives(session))
    except Exception as exc:
        session.emit_sse(
            "session_error",
            {"session_id": session.session_id, "error": str(exc)},
        )
    finally:
        session.mark_complete()


async def _prewarm_top_alternatives(session: SpatialSession) -> None:
    """Speculatively pre-render top compliant alternatives in parallel (`gemini-nano-banana-2.1`) for instant swaps."""
    try:
        if not session.scale or not session.room_images or not session.last_render_bytes:
            return
        orig_room_bytes, orig_mime = session.room_images[0]
        prior_bytes = session.last_render_bytes
        prior_inter_id = session.last_render_interaction_id
        zones = session.scale.zones

        jobs: list[tuple[ShopifySKU, ShopifySKU, Any]] = []
        for active_item in session.verified_items:
            alts = session.alternatives_by_sku.get(active_item.sku_id) or []
            for card in alts:
                if card.hook_blocked or card.sku.sku_id == active_item.sku_id:
                    continue
                zone_obj = next(
                    (z for z in zones if z.zone_id == active_item.zone_id),
                    zones[0] if zones else None,
                )
                jobs.append((active_item, card.sku, zone_obj))
                break  # Top 1 compliant alternative per active item (parallel across all items!)
            if len(jobs) >= 4:
                break

        async def _run_one(t_item: ShopifySKU, cand: ShopifySKU, z_obj: Any) -> None:
            try:
                s_bytes, s_mime, s_inter, s_refs = await render_surgical_swap(
                    room_image_bytes=orig_room_bytes,
                    prior_render_bytes=prior_bytes,
                    prior_interaction_id=prior_inter_id,
                    target_item=t_item,
                    new_sku=cand,
                    zone=z_obj,
                )
                qa = await audit_rendered_room(
                    original_room_bytes=orig_room_bytes,
                    original_mime=orig_mime,
                    sku_images=s_refs,
                    rendered_room_bytes=s_bytes,
                    rendered_mime=s_mime,
                    was_repaired=False,
                )
                session.prewarmed_swaps[(t_item.sku_id, cand.sku_id)] = (
                    s_bytes,
                    s_mime,
                    s_inter,
                    qa,
                )
            except Exception:
                pass

        if jobs:
            await asyncio.gather(*[_run_one(t, c, z) for t, c, z in jobs])
    except Exception:
        pass


async def _stream_session_events(session: SpatialSession) -> AsyncIterator[str]:
    q: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
    # Subscribe BEFORE snapshotting history so zero events can drop across yields
    session.subscribers.append(q)
    try:
        snapshot = list(session.sse_history)
        already_done = session.completed
        for ev_name, payload in snapshot:
            yield _sse_frame(ev_name, payload)
        if already_done:
            yield _sse_frame("complete", {"session_id": session.session_id})
            return

        while True:
            item = await q.get()
            if item is None:
                yield _sse_frame("complete", {"session_id": session.session_id})
                break
            ev_name, payload = item
            yield _sse_frame(ev_name, payload)
    finally:
        if q in session.subscribers:
            session.subscribers.remove(q)


@app.get("/api/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "clearbuy-spatial-compiler",
        "gemini_credentials_ready": has_live_gemini_credentials(),
        "models": {
            "scale_neon": get_model_neon(),
            "router_hydrogen": get_model_hydrogen(),
            "renderer_nano_banana": get_model_nano_banana(),
            "policy_decisions": get_model_decision(),
        },
        "shop_mcp_endpoint": get_shop_mcp_url(),
        "benchmark_results_present": EVAL_RESULTS_PATH.exists(),
    }


@app.post("/api/session/start")
async def start_session(
    images: list[UploadFile] = File(..., description="1-3 room photos (1024px JPEG/PNG)"),
    prompt: str = Form(..., description="Spoken/typed room goal"),
    budget_usd: float = Form(450.0, description="Strict maximum USD budget"),
    exif_focal_mm: float | None = Form(None, description="Optional 35mm-equivalent EXIF focal length"),
    scope: SpaceScope = Form("auto"),
    mode: str = Query("sse", description="'sse' streams events directly; 'async' returns JSON + stream_url"),
) -> Any:
    if not images:
        raise HTTPException(status_code=400, detail="At least 1 room image is required.")

    normalized_imgs: list[tuple[bytes, str]] = []
    for up in images[:3]:
        raw = await up.read()
        if not raw:
            continue
        normalized_imgs.append(_normalize_image_bytes(raw))

    if not normalized_imgs:
        raise HTTPException(status_code=400, detail="Uploaded image files were empty.")

    session_id = f"sess_{uuid.uuid4().hex[:10]}"
    session = SpatialSession(
        session_id=session_id,
        prompt=prompt,
        budget_usd=budget_usd,
        scope=scope,
        exif_focal_mm=exif_focal_mm,
        room_images=normalized_imgs,
    )
    put_session(session)
    asyncio.create_task(_run_session_pipeline(session))

    if mode == "async":
        return {
            "session_id": session_id,
            "stream_url": f"/api/session/{session_id}/stream",
        }

    return StreamingResponse(
        _stream_session_events(session),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Session-Id": session_id,
        },
    )


@app.get("/api/session/{session_id}/stream")
async def stream_session(session_id: str) -> StreamingResponse:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return StreamingResponse(
        _stream_session_events(session),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-Id": session_id,
        },
    )


@app.get("/api/session/{session_id}")
async def get_session_snapshot(session_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return {
        "session_id": session.session_id,
        "completed": session.completed,
        "prompt": session.prompt,
        "budget_usd": session.budget_usd,
        "scale": session.scale.model_dump() if session.scale else None,
        "hook_events": [h.model_dump() for h in session.hook_events],
        "cart": session.cart.model_dump() if session.cart else None,
        "versions": [
            {
                "version_id": v.version_id,
                "label": v.label,
                "decisions_qa": v.decisions_qa.model_dump(),
                "repaired": v.repaired,
            }
            for v in session.versions
        ],
    }


def _lookup_candidate_sku(session: SpatialSession, sku_id: str) -> ShopifySKU | None:
    for skus in session.candidates_by_category.values():
        for s in skus:
            if s.sku_id == sku_id or s.gid == sku_id:
                return s.model_copy(deep=True)
    for card in session.last_thread_alternatives:
        if card.sku.sku_id == sku_id or card.sku.gid == sku_id:
            return card.sku.model_copy(deep=True)
    for it in session.verified_items:
        if it.sku_id == sku_id or it.gid == sku_id:
            return it.model_copy(deep=True)
    return None


def _apply_variant_dimensions(sku: ShopifySKU, variant_title: str | None) -> None:
    """Parse W x D x H dimensions from a selected Shopify variant label (e.g. '39.4\" x 18.9\" x 29.5\"')."""
    if not variant_title:
        return
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:\"|in|inch|inches)?\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:\"|in|inch|inches)?(?:\s*[x×]\s*(\d+(?:\.\d+)?))?",
        variant_title,
        flags=re.IGNORECASE,
    )
    if not m:
        return
    w = float(m.group(1))
    d = float(m.group(2))
    h = float(m.group(3)) if m.group(3) else sku.dimensions.height_in
    # Sanity-check inches range (6" to 140")
    if 6.0 <= w <= 140.0:
        sku.dimensions.width_in = round(w, 1)
        sku.dimensions.verified = True
        sku.dimensions.raw_text = variant_title
    if 6.0 <= d <= 140.0:
        sku.dimensions.depth_in = round(d, 1)
    if h is not None and 4.0 <= h <= 120.0:
        sku.dimensions.height_in = round(h, 1)


async def execute_session_swap(session: SpatialSession, req: SwapRequest) -> SwapResponse:
    """Core `hooks.json` -> stateful Nano Banana surgical swap -> Decisions QA -> UCP update flow."""
    zones = session.scale.zones if session.scale else []
    target_item = next(
        (it for it in session.verified_items if it.sku_id == req.target_item_id),
        session.verified_items[0] if session.verified_items else None,
    )
    if not target_item:
        raise HTTPException(status_code=404, detail=f"Target item '{req.target_item_id}' not in active cart.")

    new_sku = _lookup_candidate_sku(session, req.new_sku_id)
    if not new_sku:
        raise HTTPException(status_code=404, detail=f"Candidate SKU '{req.new_sku_id}' not found in session.")

    new_sku.zone_id = req.zone_id or target_item.zone_id

    # Apply requested variant swatch if specified
    if req.variant_id:
        matched_v = next(
            (v for v in new_sku.variants if v.variant_id == req.variant_id or v.gid == req.variant_id),
            None,
        )
        if matched_v:
            new_sku.selected_variant_id = matched_v.variant_id
            new_sku.selected_variant_gid = matched_v.gid
            new_sku.price_cents = matched_v.price_cents
            new_sku.price_usd = matched_v.price_usd
            if matched_v.image_url:
                new_sku.image_url = matched_v.image_url
            _apply_variant_dimensions(new_sku, matched_v.title)

    proposed_cart = [
        (new_sku if it.sku_id == target_item.sku_id else it)
        for it in session.verified_items
    ]

    # 1. Hard `verify_bundle.py` / `hooks.json` gate BEFORE rendering or checkout update!
    hook_ev = verify_bundle_deterministic(
        session_id=session.session_id,
        zones=zones,
        proposed_items=proposed_cart,
        budget_usd=session.budget_usd,
        attempt=len(session.hook_events) + 1,
    )
    session.hook_events.append(hook_ev)
    session.emit_sse("hook_event", hook_ev.model_dump())

    if hook_ev.decision == "deny":
        raise HTTPException(
            status_code=422,
            detail={
                "message": hook_ev.reason,
                "hook_deny": hook_ev.model_dump(),
            },
        )

    # 2. Enrich variant swatches & full gallery photos via `get_product` + update UCP checkouts
    t_cart_upd = time.perf_counter()
    mcp = ShopMCPClient()
    new_sku_enriched, v_trace = await mcp.enrich_product_variants(new_sku)
    session.mcp_calls.append(v_trace)
    if req.variant_id:
        mv = next(
            (v for v in new_sku_enriched.variants if v.variant_id == req.variant_id or v.gid == req.variant_id),
            None,
        )
        if mv:
            new_sku_enriched.selected_variant_id = mv.variant_id
            new_sku_enriched.selected_variant_gid = mv.gid
            new_sku_enriched.price_cents = mv.price_cents
            new_sku_enriched.price_usd = mv.price_usd
            if mv.image_url:
                new_sku_enriched.image_url = mv.image_url
            _apply_variant_dimensions(new_sku_enriched, mv.title)

    updated_cart = annotate_item_fit_badges(
        zones,
        [
            (new_sku_enriched if it.sku_id == target_item.sku_id else it)
            for it in session.verified_items
        ],
    )
    zones = update_zone_footprints(zones, updated_cart)
    if session.scale:
        session.scale.zones = zones

    sku_tabs, alts_by_sku = build_sku_tabs_and_alternatives(
        session_id=session.session_id,
        zones=zones,
        verified_items=updated_cart,
        candidates_by_category=session.candidates_by_category,
        budget_usd=session.budget_usd,
    )
    updated_checkouts, ucp_traces = await mcp.create_or_update_merchant_checkouts(
        verified_items=updated_cart,
        existing_checkouts=session.checkouts,
    )
    session.mcp_calls.extend(ucp_traces)

    total_cents = sum(it.price_cents for it in updated_cart)
    total_usd = round(total_cents / 100.0, 2)
    swapped_final = next(
        (it for it in updated_cart if it.sku_id == new_sku_enriched.sku_id),
        new_sku_enriched,
    )

    session.verified_items = updated_cart
    session.sku_tabs = sku_tabs
    session.alternatives_by_sku = alts_by_sku
    session.checkouts = updated_checkouts

    # Emit instant `cart_ready` SSE BEFORE ~14s Nano Banana render so UI updates dimensions, tabs & checkouts in <300ms!
    cart_ev = CartReadyEvent(
        session_id=session.session_id,
        status="verified",
        verified_items=updated_cart,
        sku_tabs=sku_tabs,
        alternatives_by_sku=alts_by_sku,
        zones=zones,
        total_cents=total_cents,
        total_usd=total_usd,
        budget_usd=session.budget_usd,
        remaining_budget_usd=round(session.budget_usd - total_usd, 2),
        checkouts=updated_checkouts,
        mcp_calls=[v_trace] + ucp_traces,
        elapsed_ms=int((time.perf_counter() - t_cart_upd) * 1000),
    )
    session.cart = cart_ev
    session.emit_sse("cart_ready", cart_ev.model_dump())

    # Fast-path (`skip_render=True`, e.g. variant finish swatch toggle or instant dimension preview)
    if req.skip_render:
        session.save_metadata()
        versions_avail = [v.version_id for v in session.versions] or ["v1"]
        cur_vid = versions_avail[-1]
        return SwapResponse(
            session_id=session.session_id,
            version_id=cur_vid,
            versions_available=versions_avail,
            swapped_item=swapped_final,
            verified_items=updated_cart,
            sku_tabs=sku_tabs,
            alternatives_by_sku=alts_by_sku,
            zones=zones,
            total_usd=total_usd,
            budget_usd=session.budget_usd,
            checkouts=updated_checkouts,
            hook_event=hook_ev,
            render=None,
        )

    # 3. Stateful Nano Banana 2.1 surgical swap + `gemini-decision-1` QA (instant <150ms if pre-warmed!)
    t_swap = time.perf_counter()
    orig_room_bytes, orig_mime = session.room_images[0]
    prior_bytes = session.last_render_bytes or orig_room_bytes
    zone_obj = next((z for z in zones if z.zone_id == new_sku_enriched.zone_id), zones[0] if zones else None)

    repaired = False
    repair_reason: str | None = None
    prewarmed = (
        None
        if req.variant_id
        else session.prewarmed_swaps.pop((target_item.sku_id, new_sku_enriched.sku_id), None)
    )
    if prewarmed is not None:
        swap_bytes, swap_mime, new_inter_id, qa_verdict = prewarmed
    else:
        swap_bytes, swap_mime, new_inter_id, new_refs = await render_surgical_swap(
            room_image_bytes=orig_room_bytes,
            prior_render_bytes=prior_bytes,
            prior_interaction_id=session.last_render_interaction_id,
            target_item=target_item,
            new_sku=new_sku_enriched,
            zone=zone_obj,
        )

        qa_verdict = await audit_rendered_room(
            original_room_bytes=orig_room_bytes,
            original_mime=orig_mime,
            sku_images=new_refs,
            rendered_room_bytes=swap_bytes,
            rendered_mime=swap_mime,
            was_repaired=False,
        )

        if qa_verdict.status == "failed" and qa_verdict.defect_summary:
            repair_reason = qa_verdict.defect_summary
            swap_bytes, swap_mime, new_inter_id = await render_targeted_repair(
                room_image_bytes=orig_room_bytes,
                failed_render_bytes=swap_bytes,
                prior_interaction_id=new_inter_id,
                defect_summary=repair_reason,
            )
            repaired = True
            qa_verdict = await audit_rendered_room(
                original_room_bytes=orig_room_bytes,
                original_mime=orig_mime,
                sku_images=new_refs,
                rendered_room_bytes=swap_bytes,
                rendered_mime=swap_mime,
                was_repaired=True,
            )

    version_id = f"v{len(session.versions) + 1}"
    b64_swap = base64.b64encode(swap_bytes).decode("utf-8")
    ver = RenderVersion(
        version_id=version_id,
        label=f"{version_id} · Swapped {new_sku_enriched.category} -> {new_sku_enriched.title[:28]}",
        image_b64=b64_swap,
        image_mime=swap_mime,
        interaction_id=new_inter_id,
        decisions_qa=qa_verdict,
        repaired=repaired,
        active_sku_ids=[it.sku_id for it in updated_cart],
    )
    session.versions.append(ver)
    session.last_render_interaction_id = new_inter_id
    session.last_render_bytes = swap_bytes
    session.save_metadata()

    versions_avail = [v.version_id for v in session.versions]
    render_ev = RenderReadyEvent(
        session_id=session.session_id,
        version_id=version_id,
        versions_available=versions_avail,
        image_b64=b64_swap,
        image_mime=swap_mime,
        hotspot_pins=compute_hotspot_pins(zones, updated_cart),
        decisions_qa=qa_verdict,
        repaired=repaired,
        repair_reason=repair_reason,
        elapsed_ms=int((time.perf_counter() - t_swap) * 1000),
    )
    session.emit_sse("render_ready", render_ev.model_dump())

    return SwapResponse(
        session_id=session.session_id,
        version_id=version_id,
        versions_available=versions_avail,
        swapped_item=swapped_final,
        verified_items=updated_cart,
        sku_tabs=sku_tabs,
        alternatives_by_sku=alts_by_sku,
        zones=zones,
        total_usd=total_usd,
        budget_usd=session.budget_usd,
        checkouts=updated_checkouts,
        hook_event=hook_ev,
        render=render_ev,
    )


@app.get("/api/session/{session_id}/alternatives")
async def get_session_alternatives(
    session_id: str,
    sku_id: str | None = Query(None, description="Optional active cart SKU ID to filter alternatives"),
) -> dict[str, Any]:
    """Sub-2ms pre-vetted alternatives + multi-SKU tab inspector endpoint."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    zones = session.scale.zones if session.scale else []
    if not session.sku_tabs and session.verified_items:
        tabs, alts = build_sku_tabs_and_alternatives(
            session_id=session.session_id,
            zones=zones,
            verified_items=session.verified_items,
            candidates_by_category=session.candidates_by_category,
            budget_usd=session.budget_usd,
        )
        session.sku_tabs = tabs
        session.alternatives_by_sku = alts
    selected_alts = (
        session.alternatives_by_sku.get(sku_id, [])
        if sku_id
        else [c for cards in session.alternatives_by_sku.values() for c in cards]
    )
    return {
        "session_id": session.session_id,
        "sku_tabs": [t.model_dump() for t in session.sku_tabs],
        "alternatives": [c.model_dump() for c in selected_alts],
        "zones": [z.model_dump() for z in zones],
    }


@app.post("/api/session/{session_id}/swap", response_model=SwapResponse)
async def swap_session_item(session_id: str, req: SwapRequest) -> SwapResponse:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return await execute_session_swap(session, req)


def _is_live_checkout_id(checkout_id: str) -> bool:
    return checkout_id.startswith("gid://shopify/Checkout/") and "/local_" not in checkout_id


async def prepare_session_checkout(
    session: SpatialSession, req: CheckoutPrepareRequest
) -> CheckoutPrepareResponse:
    """Prepare live Shopify UCP checkout(s) with buyer/shipping details and generate consent token."""
    if not session.checkouts:
        raise HTTPException(
            status_code=400,
            detail="No active Shopify checkout sessions exist in this session.",
        )

    # Final deterministic spatial & budget verification before any payment authorization
    zones = session.scale.zones if session.scale else []
    if session.verified_items:
        hook_ev = verify_bundle_deterministic(
            session_id=session.session_id,
            zones=zones,
            proposed_items=session.verified_items,
            budget_usd=session.budget_usd,
            attempt=len(session.hook_events) + 1,
        )
        session.hook_events.append(hook_ev)
        if hook_ev.decision == "deny":
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"Checkout blocked by spatial/budget guardrail: {hook_ev.reason}",
                    "hook_deny": hook_ev.model_dump(),
                },
            )

    targets = (
        [c for c in session.checkouts if c.checkout_id == req.checkout_id]
        if req.checkout_id
        else list(session.checkouts)
    )
    if not targets:
        raise HTTPException(
            status_code=404,
            detail=f"Checkout '{req.checkout_id}' not found in session.",
        )

    mcp = ShopMCPClient()
    bearer = req.shop_pay_bearer_token or session.shop_pay_bearer_token
    if req.shop_pay_bearer_token:
        session.shop_pay_bearer_token = req.shop_pay_bearer_token

    updated_map: dict[str, MerchantUCPCheckout] = {c.checkout_id: c for c in session.checkouts}
    prepared_list: list[MerchantUCPCheckout] = []
    traces: list[MCPCallTrace] = []

    for chk in targets:
        if not _is_live_checkout_id(chk.checkout_id):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Checkout '{chk.checkout_id}' is not a live Shopify UCP checkout session. "
                    "Simulated or fallback permalink checkouts cannot execute live transactions."
                ),
            )
        if req.buyer is not None or req.shipping_address is not None or req.fulfillment_option_id is not None:
            try:
                upd, trace = await mcp.prepare_checkout_for_completion(
                    checkout=chk,
                    buyer=req.buyer,
                    shipping_address=req.shipping_address,
                    fulfillment_option_id=req.fulfillment_option_id,
                    bearer_token=bearer,
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Live Shopify MCP update_checkout failed for {chk.shop_domain}: {exc}",
                ) from exc
        else:
            try:
                upd, trace = await mcp.get_checkout(checkout=chk, bearer_token=bearer)
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Live Shopify MCP get_checkout failed for {chk.shop_domain}: {exc}",
                ) from exc

        updated_map[upd.checkout_id] = upd
        prepared_list.append(upd)
        traces.append(trace)

    session.checkouts = list(updated_map.values())
    session.mcp_calls.extend(traces)

    grand_total_cents = sum(
        (c.total_cents if c.total_cents > 0 else c.subtotal_cents) for c in prepared_list
    )
    grand_total_usd = round(grand_total_cents / 100.0, 2)
    requires_escalation = any(
        c.status in {"requires_escalation", "incomplete"} for c in prepared_list
    )

    confirmation_token = f"confirm_{uuid.uuid4().hex[:16]}"
    session.pending_confirmation_token = confirmation_token
    session.pending_checkout_ids = [c.checkout_id for c in prepared_list]
    session.save_metadata()

    merchant_names = ", ".join(c.merchant_name for c in prepared_list)
    consent_prompt = (
        f"Ready to place your live order with {merchant_names} for ${grand_total_usd:.2f} "
        f"(including tax and shipping). Say 'yes, confirm purchase' to authorize payment."
    )
    return CheckoutPrepareResponse(
        session_id=session.session_id,
        checkouts=prepared_list,
        grand_total_cents=grand_total_cents,
        grand_total_usd=grand_total_usd,
        requires_escalation=requires_escalation,
        consent_prompt_text=consent_prompt,
        confirmation_token=confirmation_token,
        mcp_calls=traces,
    )


async def complete_session_checkout(
    session: SpatialSession, req: CheckoutCompleteRequest
) -> CheckoutCompleteResponse:
    """Execute a live, non-simulated Shopify UCP `complete_checkout` with hard consent guardrails."""
    if not req.explicit_user_consent:
        raise HTTPException(
            status_code=400,
            detail="Explicit user consent (`explicit_user_consent=true`) is required before executing a live payment.",
        )
    if (
        not session.pending_confirmation_token
        or req.confirmation_token != session.pending_confirmation_token
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired `confirmation_token`. Call `/checkout/prepare` and obtain fresh user confirmation.",
        )

    target = next(
        (c for c in session.checkouts if c.checkout_id == req.checkout_id),
        None,
    )
    if not target:
        raise HTTPException(
            status_code=404,
            detail=f"Checkout '{req.checkout_id}' not found in session.",
        )
    if not _is_live_checkout_id(target.checkout_id):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Checkout '{target.checkout_id}' is not a live Shopify UCP checkout ID. "
                "Refusing to execute simulated/fallback transaction."
            ),
        )

    # If no live tokenized Shop Pay instrument is provided, escalate cleanly to hosted Shop Pay `continue_url`
    if req.payment_instrument is None:
        target.status = "requires_escalation"
        session.emit_sse(
            "checkout_escalation_required",
            {
                "session_id": session.session_id,
                "checkout_id": target.checkout_id,
                "shop_domain": target.shop_domain,
                "continue_url": target.continue_url,
                "reason": "Shop Pay authentication / payment instrument required via hosted continue_url.",
            },
        )
        session.save_metadata()
        total_cents = target.total_cents if target.total_cents > 0 else target.subtotal_cents
        return CheckoutCompleteResponse(
            session_id=session.session_id,
            checkout_id=target.checkout_id,
            shop_domain=target.shop_domain,
            merchant_name=target.merchant_name,
            status="requires_escalation",
            order_id=None,
            order_permalink_url=None,
            continue_url=target.continue_url,
            total_cents=total_cents,
            total_usd=round(total_cents / 100.0, 2),
            mcp_trace=None,
        )

    mcp = ShopMCPClient()
    bearer = req.shop_pay_bearer_token or session.shop_pay_bearer_token
    try:
        completed, trace = await mcp.complete_checkout(
            checkout=target,
            idempotency_key=req.idempotency_key,
            payment_instrument=req.payment_instrument,
            bearer_token=bearer,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Live Shopify MCP complete_checkout failed for {target.shop_domain}: {exc}",
        ) from exc

    session.mcp_calls.append(trace)
    session.checkouts = [
        completed if c.checkout_id == completed.checkout_id else c
        for c in session.checkouts
    ]

    if completed.status == "completed":
        session.pending_confirmation_token = None
        session.completed_orders.append(
            {
                "checkout_id": completed.checkout_id,
                "shop_domain": completed.shop_domain,
                "merchant_name": completed.merchant_name,
                "order_id": completed.order_id,
                "order_permalink_url": completed.order_permalink_url,
                "total_cents": completed.total_cents,
                "total_usd": completed.total_usd,
            }
        )
        session.emit_sse(
            "checkout_completed",
            {
                "session_id": session.session_id,
                "checkout_id": completed.checkout_id,
                "shop_domain": completed.shop_domain,
                "order_id": completed.order_id,
                "order_permalink_url": completed.order_permalink_url,
                "total_usd": completed.total_usd,
            },
        )
    else:
        session.emit_sse(
            "checkout_escalation_required",
            {
                "session_id": session.session_id,
                "checkout_id": completed.checkout_id,
                "shop_domain": completed.shop_domain,
                "status": completed.status,
                "continue_url": completed.continue_url,
            },
        )

    session.save_metadata()
    total_cents = completed.total_cents if completed.total_cents > 0 else completed.subtotal_cents
    return CheckoutCompleteResponse(
        session_id=session.session_id,
        checkout_id=completed.checkout_id,
        shop_domain=completed.shop_domain,
        merchant_name=completed.merchant_name,
        status=completed.status,
        order_id=completed.order_id,
        order_permalink_url=completed.order_permalink_url,
        continue_url=completed.continue_url,
        total_cents=total_cents,
        total_usd=round(total_cents / 100.0, 2),
        mcp_trace=trace,
    )


@app.post("/api/session/{session_id}/checkout/prepare", response_model=CheckoutPrepareResponse)
async def post_checkout_prepare(
    session_id: str, req: CheckoutPrepareRequest
) -> CheckoutPrepareResponse:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return await prepare_session_checkout(session, req)


@app.post("/api/session/{session_id}/checkout/complete", response_model=CheckoutCompleteResponse)
async def post_checkout_complete(
    session_id: str, req: CheckoutCompleteRequest
) -> CheckoutCompleteResponse:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return await complete_session_checkout(session, req)


@app.get(
    "/api/session/{session_id}/checkout/{checkout_id:path}/status",
    response_model=CheckoutCompleteResponse,
)
async def get_checkout_live_status(
    session_id: str, checkout_id: str
) -> CheckoutCompleteResponse:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    target = next((c for c in session.checkouts if c.checkout_id == checkout_id), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"Checkout '{checkout_id}' not found in session.")
    if not _is_live_checkout_id(target.checkout_id):
        raise HTTPException(
            status_code=400,
            detail=f"Checkout '{target.checkout_id}' is not a live Shopify UCP checkout ID.",
        )

    mcp = ShopMCPClient()
    try:
        refreshed, trace = await mcp.get_checkout(
            checkout=target,
            bearer_token=session.shop_pay_bearer_token,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Live Shopify MCP get_checkout failed for {target.shop_domain}: {exc}",
        ) from exc

    session.mcp_calls.append(trace)
    session.checkouts = [
        refreshed if c.checkout_id == refreshed.checkout_id else c
        for c in session.checkouts
    ]
    if refreshed.status == "completed" and not any(
        o.get("checkout_id") == refreshed.checkout_id for o in session.completed_orders
    ):
        session.completed_orders.append(
            {
                "checkout_id": refreshed.checkout_id,
                "shop_domain": refreshed.shop_domain,
                "merchant_name": refreshed.merchant_name,
                "order_id": refreshed.order_id,
                "order_permalink_url": refreshed.order_permalink_url,
                "total_cents": refreshed.total_cents,
                "total_usd": refreshed.total_usd,
            }
        )
        session.emit_sse(
            "checkout_completed",
            {
                "session_id": session.session_id,
                "checkout_id": refreshed.checkout_id,
                "shop_domain": refreshed.shop_domain,
                "order_id": refreshed.order_id,
                "order_permalink_url": refreshed.order_permalink_url,
                "total_usd": refreshed.total_usd,
            },
        )
    session.save_metadata()
    total_cents = refreshed.total_cents if refreshed.total_cents > 0 else refreshed.subtotal_cents
    return CheckoutCompleteResponse(
        session_id=session.session_id,
        checkout_id=refreshed.checkout_id,
        shop_domain=refreshed.shop_domain,
        merchant_name=refreshed.merchant_name,
        status=refreshed.status,
        order_id=refreshed.order_id,
        order_permalink_url=refreshed.order_permalink_url,
        continue_url=refreshed.continue_url,
        total_cents=total_cents,
        total_usd=round(total_cents / 100.0, 2),
        mcp_trace=trace,
    )


@app.post("/api/session/{session_id}/thread", response_model=ThreadResponse)
async def post_session_thread(session_id: str, req: ThreadRequest) -> ThreadResponse:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return await handle_thread_utterance(
        session,
        req,
        execute_session_swap,
        checkout_preparer=prepare_session_checkout,
        checkout_completer=complete_session_checkout,
    )


@app.patch("/api/session/{session_id}/zone", response_model=ZoneOverrideResponse)
async def patch_session_zone(
    session_id: str, req: ZoneOverrideRequest
) -> ZoneOverrideResponse:
    session = get_session(session_id)
    if not session or not session.scale:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' scale state not found.")

    target_zone = next(
        (z for z in session.scale.zones if z.zone_id == req.zone_id),
        session.scale.zones[0] if session.scale.zones else None,
    )
    if not target_zone:
        raise HTTPException(status_code=404, detail=f"Zone '{req.zone_id}' not found.")

    target_zone.width_in = round(req.override_width_in, 1)
    if req.override_depth_in is not None:
        target_zone.depth_in = round(req.override_depth_in, 1)
    target_zone.usable_width_in = round(
        max(8.0, target_zone.width_in - target_zone.wall_margin_in), 1
    )
    target_zone.overridden_by_user = True
    target_zone.confidence_tier = "high"
    target_zone.tolerance_in = 0.5

    hook_ev = verify_bundle_deterministic(
        session_id=session.session_id,
        zones=session.scale.zones,
        proposed_items=session.verified_items,
        budget_usd=session.budget_usd,
        attempt=len(session.hook_events) + 1,
    )
    session.hook_events.append(hook_ev)
    session.verified_items = annotate_item_fit_badges(
        session.scale.zones, session.verified_items
    )
    session.scale.zones = update_zone_footprints(
        session.scale.zones, session.verified_items
    )
    target_zone = next(
        (z for z in session.scale.zones if z.zone_id == target_zone.zone_id),
        target_zone,
    )
    sku_tabs, alts_by_sku = build_sku_tabs_and_alternatives(
        session_id=session.session_id,
        zones=session.scale.zones,
        verified_items=session.verified_items,
        candidates_by_category=session.candidates_by_category,
        budget_usd=session.budget_usd,
    )
    session.sku_tabs = sku_tabs
    session.alternatives_by_sku = alts_by_sku
    session.save_metadata()

    return ZoneOverrideResponse(
        session_id=session.session_id,
        updated_zone=target_zone,
        zones=session.scale.zones,
        hook_event=hook_ev,
        verified_items=session.verified_items,
        sku_tabs=sku_tabs,
        alternatives_by_sku=alts_by_sku,
        all_items_still_fit=(hook_ev.decision == "allow"),
    )


@app.get("/api/benchmark")
async def get_benchmark_results() -> JSONResponse:
    if EVAL_RESULTS_PATH.exists():
        data = json.loads(EVAL_RESULTS_PATH.read_text(encoding="utf-8"))
        stress_path = EVAL_RESULTS_PATH.parent / "stress_results.json"
        if stress_path.exists():
            data["stress_suite"] = json.loads(stress_path.read_text(encoding="utf-8"))
        return JSONResponse(content=data)
    return JSONResponse(
        status_code=200,
        content={
            "status": "pending_live_eval",
            "rooms_tested": 0,
            "message": "Run `uv run python eval/run_eval.py` after adding GEMINI_API_KEY in `.env.local`.",
        },
    )
