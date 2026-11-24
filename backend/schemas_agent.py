"""Frozen Pydantic v2 data contracts for ClearBuy.

Shared across the scale engine & Managed Agents, the FastAPI SSE / Shop MCP/UCP /
Nano Banana 2.1 / Decisions API / benchmark layer, and the Next.js 15 Glass-Box Studio.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


ScopeMode = Literal["auto", "nook", "upgrade", "full_room"]
ResolvedScope = Literal["nook", "upgrade", "full_room"]

AnchorTier = Literal[
    "code_invariant",
    "manufactured_standard",
    "dynamic_object",
    "architectural_variable",
]

EnclosureType = Literal[
    "enclosed_alcove",
    "corner_nook",
    "open_wall",
    "floor_island",
    "existing_surface",
    "wall_vertical",
]

ClearanceType = Literal[
    "chair_pullout",
    "walkway",
    "door_swing",
    "sofa_legroom",
    "bed_access",
    "none",
]

PlacementMode = Literal[
    "floor_anchor",
    "underlay",
    "paired_tuck",
    "surface_top",
    "wall_mount",
]

FitStatus = Literal[
    "verified_fit",
    "unverified_specs",
    "blocked_by_hook",
]


class BBox1000(BaseModel):
    """Normalized 0..1000 2D bounding box returned by Gemini 4 spatial vision."""

    y_min: float = Field(..., ge=0.0, le=1000.0)
    x_min: float = Field(..., ge=0.0, le=1000.0)
    y_max: float = Field(..., ge=0.0, le=1000.0)
    x_max: float = Field(..., ge=0.0, le=1000.0)

    @model_validator(mode="after")
    def _ensure_ordered(self) -> "BBox1000":
        if self.y_max < self.y_min:
            self.y_min, self.y_max = self.y_max, self.y_min
        if self.x_max < self.x_min:
            self.x_min, self.x_max = self.x_max, self.x_min
        return self

    def to_px(self, img_w: int, img_h: int) -> "BBoxPx":
        return BBoxPx(
            x1=round((self.x_min / 1000.0) * img_w, 2),
            y1=round((self.y_min / 1000.0) * img_h, 2),
            x2=round((self.x_max / 1000.0) * img_w, 2),
            y2=round((self.y_max / 1000.0) * img_h, 2),
        )


class BBoxPx(BaseModel):
    """Pixel-space bounding box on the resized (<=1024px) image."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width_px(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height_px(self) -> float:
        return max(0.0, self.y2 - self.y1)


class DetectedAnchor(BaseModel):
    """Physical reference anchor detected by gemini-4-neon for Layer 1 scale calibration."""

    anchor_id: str
    standard_key: Optional[str] = Field(
        default=None,
        description="Key in anchor_standards.json if matched, or None for dynamic everyday object.",
    )
    label: str = Field(..., description="Human-readable anchor name, e.g. 'US Wall Outlet' or '27\" Monitor'")
    tier: AnchorTier = "code_invariant"
    bbox_1000: BBox1000
    bbox_px: BBoxPx
    measured_axis: Literal["height", "width"] = "height"
    known_inches: float = Field(..., gt=0.0)
    axis_pixels: float = Field(..., gt=0.0)
    px_per_inch: float = Field(..., gt=0.0)
    confidence_weight: float = Field(default=0.9, ge=0.05, le=1.0)
    plane_alignment: Literal["same_plane", "adjacent_wall", "foreground", "background"] = "same_plane"
    nearest_zone_id: Optional[str] = None
    callout_text: str = Field(
        default="",
        description="Formatted CAD callout, e.g. 'US Outlet · 4.5\" H -> 14.2 px/in'",
    )


class ProtectedAnchor(BaseModel):
    """Kept existing furniture masked during 'upgrade' scope."""

    protected_id: str
    label: str
    category: str = "existing_furniture"
    bbox_1000: BBox1000
    bbox_px: BBoxPx
    estimated_width_in: Optional[float] = None
    estimated_depth_in: Optional[float] = None
    supports_surface_items: bool = True
    zone_id: Optional[str] = None


class SpatialZone(BaseModel):
    """Measured placement zone with universal spatial topology & context-driven clearance rules."""

    zone_id: str = Field(..., description="Short zone identifier, e.g. 'Z1', 'Z2'")
    angle_index: int = Field(default=0, ge=0)
    label: str = Field(..., description="Architectural zone label, e.g. 'Desk Nook' or 'Sofa Wall'")
    enclosure_type: EnclosureType = "enclosed_alcove"
    target_categories: List[str] = Field(default_factory=list)
    bbox_1000: BBox1000
    bbox_px: BBoxPx
    width_in: float = Field(..., gt=0.0)
    depth_in: float = Field(..., gt=0.0)
    height_limit_in: Optional[float] = Field(default=None)
    lateral_margin_in: float = Field(
        default=2.0,
        ge=0.0,
        description="Context-driven side buffer (2.0 in for walled alcoves, 0.5-1.0 in open wall, 0.0 in surface/rug).",
    )
    usable_width_in: float = Field(..., gt=0.0)
    clearance_type: ClearanceType = "chair_pullout"
    functional_clearance_in: float = Field(
        default=24.0,
        ge=0.0,
        description="Required pull-out/walkway/legroom clearance along depth axis (0 for static shelves/art/rugs).",
    )
    calibration_layer: Literal[1, 2] = 1
    reference_anchor_id: Optional[str] = None
    uncertainty_in: float = Field(default=1.5, gt=0.0)
    confidence_band: Literal["high", "medium", "low"] = "high"
    override_applied: bool = False


class ScaleCalibrationResult(BaseModel):
    """SSE 'scale_ready' payload emitted by scale_engine.py."""

    scope: ResolvedScope
    calibration_layer: Literal[1, 2]
    primary_anchor: Optional[DetectedAnchor] = None
    all_anchors: List[DetectedAnchor] = Field(default_factory=list)
    protected_anchors: List[ProtectedAnchor] = Field(default_factory=list)
    zones: List[SpatialZone] = Field(default_factory=list)
    px_per_inch: Optional[float] = None
    cross_anchor_skew_pct: float = 0.0
    foreshortening_flagged: bool = False
    exif_focal_mm: Optional[float] = None
    exif_assumed_default: bool = False
    exif_fx_px: Optional[float] = None
    median_depth_m: Optional[float] = None
    depth_engine_used: Optional[str] = None
    uncertainty_in: float = 1.5
    confidence_band: Literal["high", "medium", "low"] = "high"
    badge_label: str
    thinking_level: str = "xhigh"
    image_width_px: int
    image_height_px: int
    latency_ms: int = 0


class ParsedDimensions(BaseModel):
    """Structured physical dimensions & universal spatial placement parsed by gemini-4-hydrogen."""

    sku_id: str
    width_in: Optional[float] = Field(default=None, gt=0.0)
    depth_in: Optional[float] = Field(default=None, gt=0.0)
    height_in: Optional[float] = Field(default=None, gt=0.0)
    dimensions_unverified: bool = False
    placement_mode: PlacementMode = "floor_anchor"
    category: str = "furniture"
    raw_dimension_evidence: Optional[str] = None
    prompt_injection_flagged: bool = False
    parse_notes: Optional[str] = None


class CandidateSKU(BaseModel):
    """Normalized Shopify candidate SKU enriched with cents->USD & structured WxDxH."""

    sku_id: str = Field(..., description="Shopify Product GID, e.g. gid://shopify/Product/...")
    variant_id: Optional[str] = None
    title: str
    merchant_name: str = "Shopify Merchant"
    shop_domain: Optional[str] = None
    price_cents: int = Field(..., ge=0)
    price_usd: float = Field(..., ge=0.0)
    currency: str = "USD"
    in_stock: bool = True
    verified_at_unix: Optional[float] = None
    image_url: Optional[str] = None
    product_url: Optional[str] = None
    variants: List[Dict[str, Any]] = Field(default_factory=list)
    width_in: Optional[float] = None
    depth_in: Optional[float] = None
    height_in: Optional[float] = None
    dimensions_unverified: bool = False
    placement_mode: PlacementMode = "floor_anchor"
    category: str = "furniture"
    aesthetic_score: Optional[float] = None
    safety_passed: bool = True


class ProposedItem(BaseModel):
    """Single item inside /workspace/cart_proposal.json written by the Managed Agent."""

    item_id: str
    zone_id: str
    sku_id: str
    variant_id: Optional[str] = None
    title: str
    merchant_name: str = "Shopify Merchant"
    price_cents: int = Field(..., ge=0)
    price_usd: float = Field(..., ge=0.0)
    width_in: Optional[float] = None
    depth_in: Optional[float] = None
    height_in: Optional[float] = None
    dimensions_unverified: bool = False
    placement_mode: PlacementMode = "floor_anchor"
    category: str = "furniture"
    parent_anchor_id: Optional[str] = Field(
        default=None,
        description="Optional item_id or protected_id when placement_mode=='surface_top' or 'paired_tuck'.",
    )
    image_url: Optional[str] = None
    product_url: Optional[str] = None
    fit_status: FitStatus = "verified_fit"
    fit_badge_text: Optional[str] = None


class CartProposal(BaseModel):
    """Schema of /workspace/cart_proposal.json gated by .agents/hooks.json -> verify_bundle.py."""

    budget_usd: float = Field(..., gt=0.0)
    items: List[ProposedItem] = Field(default_factory=list)
    rationale: Optional[str] = None


class ViolationDetail(BaseModel):
    """Exact physical or budget violation computed deterministically by verify_bundle.py."""

    code: Literal[
        "BUDGET_EXCEEDED",
        "PRICE_MISMATCH",
        "ZONE_WIDTH_OVERFLOW",
        "UNDERLAY_OVERFLOW",
        "SURFACE_OVERFLOW",
        "WALL_MOUNT_OVERFLOW",
        "DEPTH_CLEARANCE_VIOLATION",
        "WALKWAY_CLEARANCE_VIOLATION",
        "HEIGHT_LIMIT_EXCEEDED",
        "PROTECTED_ANCHOR_COLLISION",
        "UNKNOWN_ZONE",
        "EMPTY_BUNDLE",
        "INVALID_SKU_GID",
        "UNVERIFIED_PRIMARY_DIMENSIONS",
        "CONSTRAINT_TAMPERING",
    ]
    zone_id: Optional[str] = None
    item_id: Optional[str] = None
    sku_id: Optional[str] = None
    measured_value: Optional[float] = None
    limit_value: Optional[float] = None
    overflow_amount: Optional[float] = None
    message: str


class HookTraceEvent(BaseModel):
    """SSE 'hook_event' payload showing transparent DENY -> RETRY -> ALLOW trace."""

    attempt: int = 1
    decision: Literal["allow", "deny"]
    reason: str
    total_usd: float = 0.0
    budget_usd: float = 0.0
    violations: List[ViolationDetail] = Field(default_factory=list)
    zone_summaries: Dict[str, str] = Field(default_factory=dict)
    timestamp_ms: int = 0


class SafeRefusalResult(BaseModel):
    """Clean honest refusal when physical + budget constraints are mathematically impossible."""

    is_refusal: bool = True
    reason: str
    shortfall_usd: Optional[float] = None
    min_feasible_budget_usd: Optional[float] = None
    narrowest_available_width_in: Optional[float] = None
    target_usable_width_in: Optional[float] = None
    closest_valid_alternatives: List[CandidateSKU] = Field(default_factory=list)


class BundleSolveResult(BaseModel):
    """Complete output returned by managed_agent.solve_spatial_bundle to FastAPI."""

    status: Literal["verified", "safe_refusal"]
    proposal: Optional[CartProposal] = None
    safe_refusal: Optional[SafeRefusalResult] = None
    hook_trace: List[HookTraceEvent] = Field(default_factory=list)
    self_corrected: bool = False
    denied_count: int = 0
    execution_mode: Literal["managed_agent_remote", "local_hook_sandbox"] = "managed_agent_remote"
    interaction_id: Optional[str] = None
    environment_id: Optional[str] = None
    latency_ms: int = 0


class ZoneOverrideRequest(BaseModel):
    """Request payload for PATCH /api/session/{id}/zone (user drag on CAD measuring lines)."""

    zone_id: str
    override_width_in: Optional[float] = Field(default=None, gt=2.0)
    override_depth_in: Optional[float] = Field(default=None, gt=2.0)


class ZoneOverrideResponse(BaseModel):
    """Instantaneous recalculation result for PATCH /api/session/{id}/zone."""

    updated_zone: SpatialZone
    hook_evaluation: HookTraceEvent
    updated_items: List[ProposedItem] = Field(default_factory=list)
