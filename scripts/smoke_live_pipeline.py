"""Live End-to-End Smoke Verification of the full pipeline (`mcp.shop.com` + Full Gemini 4 Suite)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.adapters import run_scale_calibration
from backend.config import EVAL_DATA_DIR, has_live_gemini_credentials
from backend.renderer import render_initial_bundle, render_surgical_swap
from backend.shop_mcp import ShopMCPClient, extract_dimensions_via_hydrogen
from backend.visual_qa import audit_rendered_room, screen_catalog_candidates


async def main() -> None:
    print("=== 1. Live Shopify `https://mcp.shop.com/` JSON-RPC ===")
    mcp = ShopMCPClient()
    skus, trace = await mcp.search_category("compact standing desk", max_price_usd=350.0, limit=4)
    print(f"  search_catalog: status={trace.status} latency={trace.latency_ms}ms returned={len(skus)}")

    if not has_live_gemini_credentials():
        print("  [STOP] GEMINI_API_KEY missing in .env.local")
        return

    print("\n=== 2. Live `gemini-4-hydrogen` WxDxH Extraction + `gemini-decision-1` Catalog Gate ===")
    parsed = await extract_dimensions_via_hydrogen(skus[:3])
    screened, dec_ms = await screen_catalog_candidates(
        prompt="Compact standing desk for apartment nook under $350",
        category="desk",
        candidates=parsed,
    )
    print(f"  screened={len(screened)} in {dec_ms}ms (0 output tokens)")
    print("  sample dims:", json.dumps(screened[0].dimensions.model_dump()))
    print("  sample gate:", json.dumps(screened[0].decisions_gate.model_dump()))

    print("\n=== 3. Live `gemini-4-neon` (`xhigh`) Scale & Anchor Calibration ===")
    sample_room_path = EVAL_DATA_DIR / "nyu_001_rgb.jpg"
    room_bytes = sample_room_path.read_bytes()
    scale_ev = await run_scale_calibration(
        session_id="smoke_neon",
        image_bytes=room_bytes,
        mime_type="image/jpeg",
        prompt="Put a compact standing desk in that empty wall stretch under $350",
        scope="nook",
        exif_focal_mm=28.0,
        thinking_level="xhigh",
    )
    print(
        f"  layer={scale_ev.calibration_layer} summary='{scale_ev.calibration_summary}' "
        f"zone_1_width={scale_ev.zones[0].width_in}\" elapsed={scale_ev.elapsed_ms}ms"
    )

    print("\n=== 4. Live `gemini-nano-banana-2.1` Render + `gemini-decision-1` 4-Rubric Visual QA ===")
    lead_sku = screened[0]
    lead_sku.zone_id = scale_ev.zones[0].zone_id
    render_bytes, render_mime, inter_id, refs = await render_initial_bundle(
        room_image_bytes=room_bytes,
        room_mime="image/jpeg",
        zones=scale_ev.zones,
        verified_items=[lead_sku],
        protected_anchors=scale_ev.protected_anchors,
    )
    print(f"  render v1 bytes={len(render_bytes)} mime={render_mime} interaction_id={inter_id}")

    qa = await audit_rendered_room(
        original_room_bytes=room_bytes,
        original_mime="image/jpeg",
        sku_images=refs,
        rendered_room_bytes=render_bytes,
        rendered_mime=render_mime,
    )
    print("  Decisions API 4-rubric QA:", json.dumps(qa.model_dump()))

    if len(screened) > 1:
        print("\n=== 5. Live Stateful Surgical Swap (`v1 -> v2`) ===")
        swap_sku = screened[1]
        swap_sku.zone_id = scale_ev.zones[0].zone_id
        swap_bytes, _, inter_2, _ = await render_surgical_swap(
            room_image_bytes=room_bytes,
            prior_render_bytes=render_bytes,
            prior_interaction_id=inter_id,
            target_item=lead_sku,
            new_sku=swap_sku,
            zone=scale_ev.zones[0],
        )
        print(f"  surgical swap v2 bytes={len(swap_bytes)} interaction_id={inter_2}")


if __name__ == "__main__":
    asyncio.run(main())
