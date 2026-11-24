"""CLI smoke & live rehearsal harness for the scale engine, spec parser & Managed Agent modules.

Usage:
    uv run python -m backend.cli_smoke_test
"""

from __future__ import annotations

import asyncio
import json
from PIL import Image, ImageDraw

from backend.managed_agent import evaluate_single_swap, solve_spatial_bundle
from backend.scale_engine import calibrate_space
from backend.spec_parser import normalize_shopify_candidates, parse_sku_dimensions_batch


def make_synthetic_nook_image(width: int = 1024, height: int = 768) -> Image.Image:
    """Create a clean architectural apartment nook image with a visible US duplex wall outlet."""
    img = Image.new("RGB", (width, height), (232, 230, 224))
    draw = ImageDraw.Draw(img)

    # Floor plane
    draw.polygon([(0, 580), (width, 580), (width, height), (0, height)], fill=(182, 152, 118))
    # Baseboard
    draw.rectangle([0, 540, width, 580], fill=(245, 245, 245), outline=(200, 200, 200))
    # Left & right alcove walls framing a ~43.5" recessed nook (x=240..820 -> 580px at ~13.3 px/in)
    draw.polygon([(0, 0), (240, 60), (240, 580), (0, 660)], fill=(210, 208, 202), outline=(170, 168, 162))
    draw.polygon([(820, 60), (width, 0), (width, 660), (820, 580)], fill=(210, 208, 202), outline=(170, 168, 162))
    draw.line([(240, 60), (240, 580)], fill=(150, 148, 142), width=3)
    draw.line([(820, 60), (820, 580)], fill=(150, 148, 142), width=3)

    # US Standard Duplex Wall Outlet on back nook wall: 4.5" H x 2.75" W -> 60px H x 37px W (13.33 px/in)
    ox1, oy1 = 340, 440
    ox2, oy2 = ox1 + 37, oy1 + 60
    draw.rectangle([ox1, oy1, ox2, oy2], fill=(250, 250, 250), outline=(120, 120, 120), width=2)
    # Two duplex sockets
    for sy in (oy1 + 12, oy1 + 34):
        draw.rounded_rectangle([ox1 + 9, sy, ox2 - 9, sy + 14], radius=4, outline=(90, 90, 90), width=2)
        draw.line([(ox1 + 14, sy + 3), (ox1 + 14, sy + 9)], fill=(50, 50, 50), width=2)
        draw.line([(ox2 - 14, sy + 3), (ox2 - 14, sy + 9)], fill=(50, 50, 50), width=2)
        draw.ellipse([ox1 + 17, sy + 10, ox1 + 20, sy + 13], fill=(50, 50, 50))

    return img


async def run_smoke() -> None:
    print("1. Running scale_engine.calibrate_space (gemini-4-neon)...")
    img = make_synthetic_nook_image()
    cal = await calibrate_space(
        image_input=img,
        prompt="Put a compact standing desk, ergonomic chair, and warm task lamp in that empty wall alcove under $450.",
        scope="nook",
        exif_focal_mm=26.0,
        thinking_level="xhigh",
    )
    print("   scale_ready badge:", cal.badge_label)
    for z in cal.zones:
        print(f"   Zone {z.zone_id} ({z.label}): {z.width_in}\" W x {z.depth_in}\" D (usable {z.usable_width_in}\")")

    raw_shop_items = [
        {
            "sku_id": "gid://shopify/Product/1001",
            "title": "Executive Standing Desk — Bargain Sale",
            "merchant_name": "Garvee Home",
            "price_cents": 16900,
            "description": {"plain": "Spacious desktop, 30\"H, 60\"W x 28\"D solid wood finish."},
        },
        {
            "sku_id": "gid://shopify/Product/1002",
            "title": "Compact Studio Standing Desk",
            "merchant_name": "Branch Furniture",
            "price_cents": 21900,
            "description": {"plain": "Ideal for NYC apartments. Overall: 36\"W x 22\"D x 29.5\"H."},
        },
        {
            "sku_id": "gid://shopify/Product/1003",
            "title": "Breathable Mesh Task Chair",
            "merchant_name": "Branch Furniture",
            "price_cents": 14900,
            "description": {"plain": "Ergonomic lumbar support. 24\"W x 23\"D x 38\"H."},
        },
        {
            "sku_id": "gid://shopify/Product/1004",
            "title": "Warm Brass Architect Desk Lamp",
            "merchant_name": "Lumens Studio",
            "price_cents": 5995,
            "description": {"plain": "Base 7\"W x 7\"D, 19\"H. Warm 2700K LED."},
        },
    ]

    print("\n2. Parsing Shopify SKU specs via spec_parser (gemini-4-hydrogen)...")
    parsed_dims = await parse_sku_dimensions_batch(raw_shop_items)
    candidates = normalize_shopify_candidates(raw_shop_items, parsed_dims)
    for c in candidates:
        print(f"   {c.title}: ${c.price_usd:.2f} | {c.width_in}\"W x {c.depth_in}\"D x {c.height_in}\"H | mode={c.placement_mode}")

    print("\n3. Solving bundle via Managed Agent + hooks.json (verify_bundle.py)...")
    result = await solve_spatial_bundle(
        user_prompt="Put a standing desk, ergonomic chair, and warm brass desk lamp in Zone Z1 under $450.",
        calibration=cal,
        budget_usd=450.0,
        candidates=candidates,
        on_hook_event=lambda ev: print(f"   [SSE hook_event #{ev.attempt}] {ev.decision.upper()}: {ev.reason}"),
    )
    print(f"   Result status={result.status} mode={result.execution_mode} latency={result.latency_ms}ms")
    if result.proposal:
        for it in result.proposal.items:
            print(f"   -> {it.title} (${it.price_usd:.2f}) [{it.fit_badge_text}]")

        print("\n4. Testing Adversarial 72\" Executive Desk Swap...")
        adv_sku = normalize_shopify_candidates(
            [
                {
                    "sku_id": "gid://shopify/Product/9999",
                    "title": "72-Inch CEO Walnut Executive Desk",
                    "merchant_name": "Executive Direct",
                    "price_cents": 39900,
                    "width_in": 72.0,
                    "depth_in": 32.0,
                    "height_in": 30.0,
                    "placement_mode": "floor_anchor",
                    "category": "desk",
                }
            ]
        )[0]
        desk_item_id = result.proposal.items[0].item_id
        allowed, _, deny_ev = evaluate_single_swap(
            current_proposal=result.proposal,
            calibration=cal,
            zone_id=cal.zones[0].zone_id,
            target_item_id=desk_item_id,
            new_sku=adv_sku,
        )
        print(f"   Swap allowed={allowed} | HTTP 422 payload: {json.dumps(deny_ev.model_dump(), indent=2)[:400]}...")


if __name__ == "__main__":
    asyncio.run(run_smoke())
