"""Automated Unit & API Contract Tests for the FastAPI orchestrator, adapters & commerce layer."""

from __future__ import annotations

from io import BytesIO
from PIL import Image
from fastapi.testclient import TestClient

from backend.adapters import solve_combinatorial_bundle, verify_bundle_deterministic
from backend.main import app
from backend.schemas import (
    BoundingBox,
    ProductDimensions,
    ShopifySKU,
    SpatialZone,
)
from backend.shop_mcp import (
    extract_plain_description,
    normalize_price_to_cents_and_usd,
    parse_dimensions_labeled_deterministic,
)


def _make_sku(
    sku_id: str,
    category: str,
    price_cents: int,
    width_in: float | None,
    depth_in: float | None = 24.0,
) -> ShopifySKU:
    return ShopifySKU(
        sku_id=sku_id,
        gid=f"gid://shopify/Product/{sku_id}",
        selected_variant_id=f"var_{sku_id}",
        selected_variant_gid=f"gid://shopify/ProductVariant/{sku_id}",
        title=f'{width_in or ""} {category.title()}'.strip(),
        category=category,
        zone_id="zone_1",
        merchant_name="Test Merchant",
        shop_domain="test-merchant.myshopify.com",
        price_cents=price_cents,
        price_usd=round(price_cents / 100.0, 2),
        image_url="https://cdn.shopify.com/s/files/1/test.jpg",
        dimensions=ProductDimensions(
            width_in=width_in,
            depth_in=depth_in,
            height_in=29.5,
            dimensions_unverified=(width_in is None),
        ),
        verified_at="2026-11-21T16:00:00Z",
    )


def test_shopify_minor_unit_cents_normalization() -> None:
    assert normalize_price_to_cents_and_usd(12995) == (12995, 129.95)
    assert normalize_price_to_cents_and_usd({"amount": 21299, "currency": "USD"}) == (21299, 212.99)
    assert normalize_price_to_cents_and_usd("149.50") == (14950, 149.50)
    assert normalize_price_to_cents_and_usd("14950") == (14950, 149.50)


def test_nested_description_and_30h_regex_trap_guard() -> None:
    desc = extract_plain_description({"plain": "<p>Ergonomic frame, <b>30\"H</b> steel legs.</p>"})
    assert desc == 'Ergonomic frame, 30"H steel legs.'

    # Must NOT confuse 30"H for width!
    dims = parse_dimensions_labeled_deterministic("Modern Work Desk", desc)
    assert dims.height_in == 30.0
    assert dims.width_in is None
    assert dims.dimensions_unverified is True

    # Must extract true labeled W x D x H
    dims_full = parse_dimensions_labeled_deterministic(
        'Compact Standing Desk', 'Overall dimensions: 40"W x 24"D x 29.5"H solid oak.'
    )
    assert dims_full.width_in == 40.0
    assert dims_full.depth_in == 24.0
    assert dims_full.height_in == 29.5
    assert dims_full.dimensions_unverified is False


def test_verify_bundle_denies_oversized_and_auto_swaps() -> None:
    zone = SpatialZone(
        zone_id="zone_1",
        label="Zone 1 · Nook",
        target_categories=["desk", "chair"],
        bbox=BoundingBox(y_min=300, x_min=200, y_max=850, x_max=750),
        width_in=43.5,
        depth_in=60.0,
        usable_width_in=41.5,
    )
    desk_48 = _make_sku("d48", "desk", 22000, width_in=48.0, depth_in=24.0)
    desk_40 = _make_sku("d40", "desk", 19900, width_in=40.0, depth_in=24.0)
    chair_ok = _make_sku("c25", "chair", 16500, width_in=25.0, depth_in=24.0)

    deny_ev = verify_bundle_deterministic("s1", [zone], [desk_48, chair_ok], budget_usd=450.0)
    assert deny_ev.decision == "deny"
    assert "48.0\" desk exceeds 43.5\"" in deny_ev.reason

    bundle, trace, refusal = solve_combinatorial_bundle(
        session_id="s1",
        zones=[zone],
        candidates_by_category={"desk": [desk_48, desk_40], "chair": [chair_ok]},
        budget_usd=450.0,
    )
    assert refusal is None
    assert [it.sku_id for it in bundle] == ["d40", "c25"]
    assert trace[0].decision == "deny"
    assert trace[-1].decision == "allow"


def test_fastapi_endpoints_health_zone_and_422_swap(monkeypatch) -> None:
    # Keep unit contract test offline & deterministic even when `.env.local` has a live key
    from backend import config, shop_mcp

    monkeypatch.setattr(config, "has_live_gemini_credentials", lambda: False)
    monkeypatch.setattr("backend.adapters.has_live_gemini_credentials", lambda: False)
    monkeypatch.setattr("backend.renderer.has_live_gemini_credentials", lambda: False)
    monkeypatch.setattr("backend.visual_qa.has_live_gemini_credentials", lambda: False)
    monkeypatch.setattr("backend.shop_mcp.has_live_gemini_credentials", lambda: False)

    async def _fake_search(self, category: str, style_hint: str = "", max_price_usd=None, limit: int = 8):
        from backend.schemas import MCPCallTrace

        if category == "desk":
            skus = [
                _make_sku("desk_48", "desk", 24000, 48.0),
                _make_sku("desk_40", "desk", 18995, 40.0),
            ]
        else:
            skus = [
                _make_sku("chair_1", "chair", 14900, 24.5),
                _make_sku("chair_2", "chair", 15900, 25.0),
            ]
        return skus, MCPCallTrace(
            call_id="c1",
            tool_name="search_catalog",
            endpoint="https://mcp.shop.com/",
            arguments={"query": category},
            latency_ms=42,
        )

    async def _fake_enrich(self, sku):
        from backend.schemas import MCPCallTrace

        return sku, MCPCallTrace(
            call_id="c2",
            tool_name="get_product",
            endpoint="https://mcp.shop.com/",
            arguments={"id": sku.gid},
            latency_ms=25,
        )

    monkeypatch.setattr(shop_mcp.ShopMCPClient, "search_category", _fake_search)
    monkeypatch.setattr(shop_mcp.ShopMCPClient, "enrich_product_variants", _fake_enrich)

    client = TestClient(app)
    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "ok"

    img = Image.new("RGB", (640, 480), (220, 220, 220))
    buf = BytesIO()
    img.save(buf, format="JPEG")

    r_start = client.post(
        "/api/session/start",
        data={
            "prompt": "Put a compact standing desk and ergonomic chair under $450",
            "budget_usd": "450",
            "scope": "nook",
        },
        files=[("images", ("room.jpg", buf.getvalue(), "image/jpeg"))],
    )
    assert r_start.status_code == 200
    session_id = r_start.headers["x-session-id"]
    sse_body = r_start.text
    assert "event: scale_ready" in sse_body
    assert "event: catalog_ready" in sse_body
    assert "event: hook_event" in sse_body
    assert "event: cart_ready" in sse_body
    assert "event: render_ready" in sse_body

    # Attempting to swap to oversized 48" desk must return HTTP 422 with hook_deny!
    r_bad_swap = client.post(
        f"/api/session/{session_id}/swap",
        json={
            "zone_id": "zone_1",
            "target_item_id": "desk_40",
            "new_sku_id": "desk_48",
        },
    )
    assert r_bad_swap.status_code == 422
    assert r_bad_swap.json()["detail"]["hook_deny"]["decision"] == "deny"

    # Valid chair swap -> returns v2!
    r_good_swap = client.post(
        f"/api/session/{session_id}/swap",
        json={
            "zone_id": "zone_1",
            "target_item_id": "chair_1",
            "new_sku_id": "chair_2",
        },
    )
    assert r_good_swap.status_code == 200
    assert r_good_swap.json()["version_id"] == "v2"

    # Measure drag override PATCH /zone
    r_zone = client.patch(
        f"/api/session/{session_id}/zone",
        json={"zone_id": "zone_1", "override_width_in": 52.0},
    )
    assert r_zone.status_code == 200
    assert r_zone.json()["updated_zone"]["usable_width_in"] == 50.0


def _seed_live_checkout_session(
    session_id: str,
    checkout_id: str = "gid://shopify/Checkout/live_abc123",
    shop_pay_token: str | None = None,
):
    from backend.schemas import MerchantUCPCheckout
    from backend.session_store import SpatialSession, put_session

    sku = _make_sku("desk_40", "desk", 18995, 40.0)
    chk = MerchantUCPCheckout(
        merchant_name="Nordic Oak Studio",
        shop_domain="nordic-oak.myshopify.com",
        checkout_id=checkout_id,
        status="incomplete",
        line_item_gids=[sku.selected_variant_gid],
        item_titles=[sku.title],
        item_count=1,
        subtotal_cents=18995,
        subtotal_usd=189.95,
        total_cents=18995,
        total_usd=189.95,
        continue_url="https://nordic-oak.myshopify.com/checkouts/cn/live_abc123",
        shop_pay_supported=True,
        payment_handlers=["dev.shopify.shop_pay"],
    )
    sess = SpatialSession(
        session_id=session_id,
        prompt="compact standing desk under $450",
        budget_usd=450.0,
        verified_items=[sku],
        checkouts=[chk],
        shop_pay_token=shop_pay_token,
    )
    put_session(sess)
    return sess


def test_complete_checkout_rejects_without_explicit_consent() -> None:
    sess = _seed_live_checkout_session("sess_consent_guard")
    sess.pending_confirmation_token = "confirm_valid123"
    client = TestClient(app)

    r_no_consent = client.post(
        f"/api/session/{sess.session_id}/checkout/complete",
        json={
            "checkout_id": "gid://shopify/Checkout/live_abc123",
            "confirmation_token": "confirm_valid123",
            "explicit_user_consent": False,
            "idempotency_key": "11111111-2222-3333-4444-555555555555",
        },
    )
    assert r_no_consent.status_code == 400
    assert "Explicit user consent" in r_no_consent.json()["detail"]

    r_bad_tok = client.post(
        f"/api/session/{sess.session_id}/checkout/complete",
        json={
            "checkout_id": "gid://shopify/Checkout/live_abc123",
            "confirmation_token": "confirm_wrong",
            "explicit_user_consent": True,
            "idempotency_key": "11111111-2222-3333-4444-555555555555",
        },
    )
    assert r_bad_tok.status_code == 400
    assert "confirmation_token" in r_bad_tok.json()["detail"]


def test_complete_checkout_rejects_local_fallback_id() -> None:
    sess = _seed_live_checkout_session(
        "sess_local_reject",
        checkout_id="gid://shopify/Checkout/local_deadbeef",
    )
    sess.pending_confirmation_token = "confirm_local123"
    client = TestClient(app)

    r = client.post(
        f"/api/session/{sess.session_id}/checkout/complete",
        json={
            "checkout_id": "gid://shopify/Checkout/local_deadbeef",
            "confirmation_token": "confirm_local123",
            "explicit_user_consent": True,
            "idempotency_key": "11111111-2222-3333-4444-555555555555",
            "payment_instrument": {"shop_token": "st_live_987654"},
        },
    )
    assert r.status_code == 400
    assert "not a live Shopify UCP checkout ID" in r.json()["detail"]


def test_complete_checkout_returns_continue_url_when_no_shop_token() -> None:
    sess = _seed_live_checkout_session("sess_escalate_url")
    sess.pending_confirmation_token = "confirm_esc123"
    client = TestClient(app)

    r = client.post(
        f"/api/session/{sess.session_id}/checkout/complete",
        json={
            "checkout_id": "gid://shopify/Checkout/live_abc123",
            "confirmation_token": "confirm_esc123",
            "explicit_user_consent": True,
            "idempotency_key": "22222222-2222-3333-4444-555555555555",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "requires_escalation"
    assert body["order_id"] is None
    assert body["continue_url"] == "https://nordic-oak.myshopify.com/checkouts/cn/live_abc123"


def test_complete_checkout_sends_exact_ucp_payload_and_emits_order(monkeypatch) -> None:
    from backend import shop_mcp

    captured_calls: list[dict] = []

    async def _fake_call_mcp_tool(self, client, tool_name, arguments, bearer_token=None):
        captured_calls.append(
            {"tool_name": tool_name, "arguments": arguments, "bearer_token": bearer_token}
        )
        if tool_name == "update_checkout":
            return (
                {
                    "id": "gid://shopify/Checkout/live_abc123",
                    "status": "ready_for_complete",
                    "continue_url": "https://nordic-oak.myshopify.com/checkouts/cn/live_abc123",
                    "totals": [
                        {"type": "subtotal", "amount": 18995},
                        {"type": "shipping", "amount": 1500},
                        {"type": "tax", "amount": 1620},
                        {"type": "total", "amount": 22115},
                    ],
                    "ucp": {"version": "2026-08-25", "payment_handlers": {"dev.shopify.shop_pay": {}}},
                },
                38,
            )
        if tool_name == "complete_checkout":
            return (
                {
                    "id": "gid://shopify/Checkout/live_abc123",
                    "status": "completed",
                    "continue_url": "https://nordic-oak.myshopify.com/checkouts/cn/live_abc123",
                    "totals": [{"type": "total", "amount": 22115}],
                    "order": {
                        "id": "gid://shopify/Order/9988776655",
                        "permalink_url": "https://nordic-oak.myshopify.com/orders/9988776655",
                    },
                    "ucp": {"version": "2026-08-25"},
                },
                61,
            )
        raise AssertionError(f"Unexpected tool: {tool_name}")

    monkeypatch.setattr(shop_mcp.ShopMCPClient, "_call_mcp_tool", _fake_call_mcp_tool)
    sess = _seed_live_checkout_session("sess_live_order")
    client = TestClient(app)

    r_prep = client.post(
        f"/api/session/{sess.session_id}/checkout/prepare",
        json={
            "buyer": {"email": "alex@example.com", "first_name": "Alex", "last_name": "Rivera"},
            "shipping_address": {
                "address1": "123 Market St",
                "city": "San Francisco",
                "province_code": "CA",
                "postal_code": "94105",
                "country_code": "US",
            },
        },
    )
    assert r_prep.status_code == 200
    prep = r_prep.json()
    assert prep["grand_total_usd"] == 221.15
    assert prep["requires_escalation"] is False
    confirm_tok = prep["confirmation_token"]

    idem = "33333333-4444-5555-6666-777777777777"
    r_comp = client.post(
        f"/api/session/{sess.session_id}/checkout/complete",
        json={
            "checkout_id": "gid://shopify/Checkout/live_abc123",
            "confirmation_token": confirm_tok,
            "explicit_user_consent": True,
            "idempotency_key": idem,
            "payment_instrument": {"shop_token": "st_live_secret_token"},
            "shop_pay_bearer_token": "sp_bearer_abc",
        },
    )
    assert r_comp.status_code == 200
    comp = r_comp.json()
    assert comp["status"] == "completed"
    assert comp["order_id"] == "gid://shopify/Order/9988776655"
    assert comp["order_permalink_url"] == "https://nordic-oak.myshopify.com/orders/9988776655"
    assert comp["total_usd"] == 221.15

    # Verify exact UCP wire payload and secret redaction in trace
    comp_call = next(c for c in captured_calls if c["tool_name"] == "complete_checkout")
    assert comp_call["bearer_token"] == "sp_bearer_abc"
    assert comp_call["arguments"]["meta"]["idempotency-key"] == idem
    assert "profile" in comp_call["arguments"]["meta"]["ucp-agent"]
    assert comp_call["arguments"]["id"] == "gid://shopify/Checkout/live_abc123"
    inst = comp_call["arguments"]["checkout"]["payment"]["instruments"][0]
    assert inst["handler_id"] == "shop_pay"
    assert inst["credential"] == {"type": "shop_token", "token": "st_live_secret_token"}
    assert comp["mcp_trace"]["arguments"]["checkout"]["payment"]["instruments"][0]["credential"]["token"] == "***REDACTED***"


def test_voice_two_step_checkout_flow(monkeypatch) -> None:
    from backend import shop_mcp

    async def _fake_call_mcp_tool(self, client, tool_name, arguments, bearer_token=None):
        if tool_name == "get_checkout":
            return (
                {
                    "id": "gid://shopify/Checkout/live_voice_01",
                    "status": "ready_for_complete",
                    "continue_url": "https://nordic-oak.myshopify.com/checkouts/cn/live_voice_01",
                    "totals": [{"type": "total", "amount": 20450}],
                },
                29,
            )
        raise AssertionError(f"Unexpected tool: {tool_name}")

    monkeypatch.setattr(shop_mcp.ShopMCPClient, "_call_mcp_tool", _fake_call_mcp_tool)
    sess = _seed_live_checkout_session(
        "sess_voice_buy",
        checkout_id="gid://shopify/Checkout/live_voice_01",
    )
    client = TestClient(app)

    # Turn 1: user says product is a good fit -> prepares live checkout & requests consent (no charge yet)
    r1 = client.post(
        f"/api/session/{sess.session_id}/thread",
        json={"utterance": "That desk is a good fit, let's buy it"},
    )
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["intent"] == "checkout_confirmation_needed"
    assert "$204.50" in b1["reply"]
    assert sess.pending_confirmation_token is not None

    # Turn 2: user confirms -> without a shop_token, cleanly returns live Shop Pay continue_url
    r2 = client.post(
        f"/api/session/{sess.session_id}/thread",
        json={"utterance": "Yes, confirm purchase"},
    )
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["intent"] == "checkout_auth_required"
    assert b2["checkout_complete"]["status"] == "requires_escalation"
    assert "https://nordic-oak.myshopify.com/checkouts/cn/live_voice_01" in b2["reply"]
