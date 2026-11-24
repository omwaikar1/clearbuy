"""Frozen API & SSE Data Contracts for ClearBuy.

Matches Section 04 ("Frozen API Contracts", Page 17) and Section 03 HCI specs:
- POST /api/session/start -> SSE (`scale_ready`, `catalog_ready`, `hook_event`, `cart_ready`, `render_ready`)
- POST /api/session/{id}/thread
- POST /api/session/{id}/swap
- PATCH /api/session/{id}/zone
- GET /api/benchmark
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

SpaceScope = Literal["auto", "nook", "upgrade", "full_room"]
FitStatus = Literal["verified_fit", "unverified_specs", "blocked_by_hook"]
QAStatus = Literal["verified", "borderline", "repaired", "failed"]


class BoundingBox(BaseModel):
    """Normalized 0-1000 `[y_min, x_min, y_max, x_max]` bounding box."""

    y_min: float = Field(..., ge=0, le=1000)
    x_min: float = Field(..., ge=0, le=1000)
    y_max: float = Field(..., ge=0, le=1000)
    x_max: float = Field(..., ge=0, le=1000)

    def as_list(self) -> list[float]:
        return [self.y_min, self.x_min, self.y_max, self.x_max]


class ReferenceAnchor(BaseModel):
    anchor_id: str
    label: str  # e.g., "US Outlet · 4.5\" H"
    anchor_type: Literal["outlet", "door", "desk", "baseboard", "other"] = "outlet"
    known_inches: float
    measured_axis: Literal["height", "width"] = "height"
    px_per_in: float
    bbox: BoundingBox


class ProtectedAnchor(BaseModel):
    label: str
    bbox: BoundingBox


class SpatialZone(BaseModel):
    zone_id: str  # e.g., "zone_1"
    label: str  # e.g., "Zone 1 · Desk Wall"
    target_categories: list[str] = Field(default_factory=list)
    bbox: BoundingBox
    width_in: float
    depth_in: float
    clearance_required_in: float = 24.0
    wall_margin_in: float = 2.0
    usable_width_in: float
    occupied_width_in: float = 0.0
    remaining_width_in: float | None = None
    occupied_depth_in: float = 0.0
    remaining_clearance_in: float | None = None
    confidence_tier: Literal["high", "medium", "low"] = "high"
    tolerance_in: float = 1.5
    overridden_by_user: bool = False


class ScaleReadyEvent(BaseModel):
    session_id: str
    detected_scope: SpaceScope
    calibration_layer: Literal[1, 2]
    calibration_summary: str  # e.g., "US Outlet · 4.5\" H -> 14.2 px/in"
    fallback_badge: str | None = None
    primary_anchor: ReferenceAnchor | None = None
    anchors_detected: list[ReferenceAnchor] = Field(default_factory=list)
    cross_anchor_skew_pct: float = 0.0
    foreshortening_warning: bool = False
    zones: list[SpatialZone]
    protected_anchors: list[ProtectedAnchor] = Field(default_factory=list)
    elapsed_ms: int = 0


class ProductDimensions(BaseModel):
    width_in: float | None = None
    depth_in: float | None = None
    height_in: float | None = None
    dimensions_unverified: bool = False
    raw_dimension_text: str | None = None


class ProductVariant(BaseModel):
    variant_id: str
    gid: str
    title: str
    sku_code: str | None = None
    option_values: dict[str, str] = Field(default_factory=dict)
    price_cents: int
    price_usd: float
    available: bool = True
    image_url: str | None = None
    gallery_images: list[str] = Field(default_factory=list)


class DecisionsCatalogGate(BaseModel):
    passed: bool = True
    category_match_prob: float = 1.0
    safe_listing_prob: float = 1.0
    harmony_score: int = 3  # 0..3
    confidence: float = 0.9


class ShopifySKU(BaseModel):
    sku_id: str
    gid: str  # e.g., "gid://shopify/Product/..."
    merchant_sku: str | None = None
    selected_variant_id: str
    selected_variant_gid: str
    title: str
    category: str  # e.g., "desk", "chair", "lamp", "shelf", "rug"
    zone_id: str | None = None
    merchant_name: str
    shop_domain: str
    price_cents: int
    price_usd: float
    currency: str = "USD"
    image_url: str
    images: list[str] = Field(default_factory=list)
    product_url: str | None = None
    description_plain: str = ""
    top_features: list[str] = Field(default_factory=list)
    dimensions: ProductDimensions = Field(default_factory=ProductDimensions)
    fit_status: FitStatus = "verified_fit"
    fit_badge_text: str = ""
    fit_margin_in: float | None = None
    in_stock: bool = True
    verified_at: str  # ISO-8601 timestamp (Shopify 10-min freshness rule)
    variants: list[ProductVariant] = Field(default_factory=list)
    decisions_gate: DecisionsCatalogGate = Field(default_factory=DecisionsCatalogGate)


class MCPCallTrace(BaseModel):
    call_id: str
    tool_name: str  # search_catalog | get_product | create_checkout | update_checkout
    endpoint: str
    arguments: dict[str, Any]
    status: Literal["ok", "fallback", "error"] = "ok"
    gids_returned: list[str] = Field(default_factory=list)
    latency_ms: int
    raw_preview: dict[str, Any] = Field(default_factory=dict)


class CatalogReadyEvent(BaseModel):
    session_id: str
    queries_executed: list[str]
    stores_scanned: int
    candidates_count: int
    mcp_calls: list[MCPCallTrace]
    candidates_by_category: dict[str, list[ShopifySKU]]
    decisions_gate_latency_ms: int = 0
    elapsed_ms: int = 0


class HookViolation(BaseModel):
    rule: Literal["wall_width", "zone_depth", "walkway_clearance", "budget_cap"]
    zone_id: str | None = None
    sku_id: str | None = None
    sku_title: str | None = None
    overflow_in: float | None = None
    over_budget_usd: float | None = None
    message: str


class HookEvent(BaseModel):
    session_id: str
    attempt: int
    decision: Literal["deny", "allow"]
    reason: str
    proposed_sku_ids: list[str] = Field(default_factory=list)
    proposed_titles: list[str] = Field(default_factory=list)
    proposed_total_usd: float = 0.0
    budget_usd: float = 0.0
    violations: list[HookViolation] = Field(default_factory=list)
    remediation_hint: str | None = None


CheckoutStatus = Literal[
    "incomplete",
    "ready_for_complete",
    "requires_escalation",
    "completed",
    "canceled",
]


class BuyerInfo(BaseModel):
    email: str
    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None


class ShippingAddress(BaseModel):
    address1: str
    address2: str | None = None
    city: str
    province_code: str
    postal_code: str
    country_code: str = "US"


class ShopPayInstrument(BaseModel):
    handler_id: str = "shop_pay"
    type: str = "shop_pay"
    shop_token: str = Field(..., min_length=4, description="Live tokenized Shop Pay credential")


class MerchantUCPCheckout(BaseModel):
    merchant_name: str
    shop_domain: str
    checkout_id: str
    status: CheckoutStatus = "incomplete"
    line_item_gids: list[str]
    item_titles: list[str]
    item_count: int
    subtotal_cents: int
    subtotal_usd: float
    tax_cents: int = 0
    shipping_cents: int = 0
    total_cents: int = 0
    total_usd: float = 0.0
    currency: str = "USD"
    continue_url: str
    shop_pay_supported: bool = True
    payment_handlers: list[str] = Field(default_factory=list)
    order_id: str | None = None
    order_permalink_url: str | None = None
    protocol_method: str = "ucp/mcp:create_checkout"
    raw_ucp_payload: dict[str, Any] = Field(default_factory=dict)


class CheckoutPrepareRequest(BaseModel):
    checkout_id: str | None = None
    buyer: BuyerInfo | None = None
    shipping_address: ShippingAddress | None = None
    fulfillment_option_id: str | None = None
    shop_pay_bearer_token: str | None = None


class CheckoutPrepareResponse(BaseModel):
    session_id: str
    checkouts: list[MerchantUCPCheckout]
    grand_total_cents: int
    grand_total_usd: float
    requires_escalation: bool = False
    consent_prompt_text: str
    confirmation_token: str
    mcp_calls: list[MCPCallTrace] = Field(default_factory=list)


class CheckoutCompleteRequest(BaseModel):
    checkout_id: str
    confirmation_token: str
    explicit_user_consent: bool
    idempotency_key: str = Field(..., min_length=8)
    payment_instrument: ShopPayInstrument | None = None
    shop_pay_bearer_token: str | None = None


class CheckoutCompleteResponse(BaseModel):
    session_id: str
    checkout_id: str
    shop_domain: str
    merchant_name: str
    status: CheckoutStatus
    order_id: str | None = None
    order_permalink_url: str | None = None
    continue_url: str
    total_cents: int = 0
    total_usd: float = 0.0
    mcp_trace: MCPCallTrace | None = None


class ThreadAlternativeCard(BaseModel):
    rank: int
    sku: ShopifySKU
    target_zone_id: str
    target_item_id: str | None = None
    price_delta_usd: float
    width_delta_in: float | None = None
    delta_badge: str  # e.g., "-$32.00 · Fits 25.0\" W"
    hook_blocked: bool = False
    block_reason: str | None = None


class SKUTabPanel(BaseModel):
    tab_index: int
    tab_id: str
    tab_label: str  # e.g., "#1 · Desk"
    zone_id: str
    zone_label: str
    active_sku: ShopifySKU
    alternatives: list[ThreadAlternativeCard] = Field(default_factory=list)


class CartReadyEvent(BaseModel):
    session_id: str
    status: Literal["verified", "safe_refusal"] = "verified"
    refusal_reason: str | None = None
    verified_items: list[ShopifySKU]
    sku_tabs: list[SKUTabPanel] = Field(default_factory=list)
    alternatives_by_sku: dict[str, list[ThreadAlternativeCard]] = Field(default_factory=dict)
    zones: list[SpatialZone] = Field(default_factory=list)
    total_cents: int
    total_usd: float
    budget_usd: float
    remaining_budget_usd: float
    checkouts: list[MerchantUCPCheckout]
    mcp_calls: list[MCPCallTrace] = Field(default_factory=list)
    elapsed_ms: int = 0


class HotspotPin(BaseModel):
    pin_number: int
    sku_id: str
    zone_id: str
    label: str
    x_norm: float  # 0..1000
    y_norm: float  # 0..1000


class DecisionsQAVerdict(BaseModel):
    no_clipping: bool
    no_clipping_prob: float
    room_preserved: bool
    room_preserved_prob: float
    scale_honest: bool
    scale_honest_prob: float
    sku_fidelity: int  # 0..3
    min_confidence: float
    status: QAStatus
    status_notice: str | None = None
    defect_summary: str | None = None
    latency_ms: int
    output_tokens: int = 0


class RenderVersion(BaseModel):
    version_id: str  # "v1", "v2", ...
    label: str
    image_b64: str
    image_mime: str = "image/jpeg"
    interaction_id: str | None = None
    decisions_qa: DecisionsQAVerdict
    repaired: bool = False
    active_sku_ids: list[str] = Field(default_factory=list)


class RenderReadyEvent(BaseModel):
    session_id: str
    version_id: str
    versions_available: list[str]
    image_b64: str
    image_mime: str = "image/jpeg"
    hotspot_pins: list[HotspotPin]
    decisions_qa: DecisionsQAVerdict
    repaired: bool = False
    repair_reason: str | None = None
    elapsed_ms: int = 0


class ThreadRequest(BaseModel):
    utterance: str
    pinned_zone_id: str | None = None
    pinned_item_id: str | None = None


class SwapRequest(BaseModel):
    zone_id: str
    target_item_id: str
    new_sku_id: str
    variant_id: str | None = None
    skip_render: bool = False


class SwapResponse(BaseModel):
    session_id: str
    version_id: str
    versions_available: list[str]
    swapped_item: ShopifySKU
    verified_items: list[ShopifySKU]
    sku_tabs: list[SKUTabPanel] = Field(default_factory=list)
    alternatives_by_sku: dict[str, list[ThreadAlternativeCard]] = Field(default_factory=dict)
    zones: list[SpatialZone] = Field(default_factory=list)
    total_usd: float
    budget_usd: float
    checkouts: list[MerchantUCPCheckout]
    hook_event: HookEvent
    render: RenderReadyEvent | None = None


class ThreadResponse(BaseModel):
    session_id: str
    intent: Literal[
        "alternatives",
        "adversarial_blocked",
        "swap_executed",
        "clarification",
        "checkout_confirmation_needed",
        "checkout_completed",
        "checkout_auth_required",
    ]
    reply: str
    scope_chip: str | None = None
    alternatives: list[ThreadAlternativeCard] = Field(default_factory=list)
    executed_swap: SwapResponse | None = None
    checkout_prepare: CheckoutPrepareResponse | None = None
    checkout_complete: CheckoutCompleteResponse | None = None


class ZoneOverrideRequest(BaseModel):
    zone_id: str
    override_width_in: float
    override_depth_in: float | None = None


class ZoneOverrideResponse(BaseModel):
    session_id: str
    updated_zone: SpatialZone
    zones: list[SpatialZone]
    hook_event: HookEvent
    verified_items: list[ShopifySKU]
    sku_tabs: list[SKUTabPanel] = Field(default_factory=list)
    alternatives_by_sku: dict[str, list[ThreadAlternativeCard]] = Field(default_factory=dict)
    all_items_still_fit: bool


# Re-export non-colliding internal solver & calibration models
from backend.schemas_agent import (  # noqa: E402, F401
    AnchorTier,
    BBox1000,
    BBoxPx,
    BundleSolveResult,
    CandidateSKU,
    CartProposal,
    ClearanceType,
    DetectedAnchor,
    EnclosureType,
    HookTraceEvent,
    ParsedDimensions,
    PlacementMode,
    ProposedItem,
    ResolvedScope,
    SafeRefusalResult,
    ScaleCalibrationResult,
    ScopeMode,
    ViolationDetail,
)
