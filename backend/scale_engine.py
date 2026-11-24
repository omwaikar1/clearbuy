"""Universal Two-Layer Zero-Measurement Scale Engine (`scale_engine.py`).

Layer 1 (Primary, High Confidence ±1.5" to ±2.5"):
  - `gemini-4-neon` (`thinking_level="xhigh"`, or `"low"` for ablation) detects:
    1. Auto-classified space scope (`nook` | `upgrade` | `full_room`).
    2. All target placement zones (`[y_min, x_min, y_max, x_max]` on 0..1000 grid) with
       universal enclosure geometry and context-driven clearance parameters.
    3. Two-Tier Reference Anchors: matches invariant building/manufacturing standards
       from `anchor_standards.json` PLUS dynamically recognized everyday manufactured
       objects (monitors, laptops, appliances, tiles, furniture) with axis-specific
       pixel measurements and baseboard variance protection.
    4. `ProtectedAnchor` masks for kept furniture in `upgrade` mode.
  - Deterministic Python computes `px_per_inch` independently per anchor and runs a
    Weighted Cross-Anchor Skew Check (`>15%` flags perspective foreshortening).

Layer 2 (Fallback, Medium Confidence ±3.8"):
  - Fires automatically when zero reliable anchors are visible (e.g., blank wall).
  - Combines `Depth-Anything-V2-Metric-Indoor-Small-hf` median depth `Z_median` (meters)
    inside the target zone box (with non-blocking optical depth fallback if offline) and
    rotation-invariant camera EXIF 35mm-equiv focal length `f_px`:
      `zone_width_m = (zone_box_width_px * Z_median) / f_px`
      `zone_width_in = zone_width_m * 39.3701`
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import os
import statistics
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union

import numpy as np
from PIL import ExifTags, Image
from pydantic import BaseModel, Field

from agents.verify_bundle import verify_bundle_dict
from backend import config as _backend_config
from backend.genai_client import (
    MODEL_NEON,
    MODEL_TRANSCRIBE,
    assert_supported_model,
    get_genai_client,
)
from backend.schemas import (
    BoundingBox,
    ProtectedAnchor as ApiProtectedAnchor,
    ReferenceAnchor as ApiReferenceAnchor,
    ScaleReadyEvent,
    SpatialZone as ApiSpatialZone,
)
from backend.schemas_agent import (
    AnchorTier,
    BBox1000,
    BBoxPx,
    ClearanceType,
    DetectedAnchor,
    EnclosureType,
    HookTraceEvent,
    ProposedItem,
    ProtectedAnchor,
    ResolvedScope,
    ScaleCalibrationResult,
    ScopeMode,
    SpatialZone,
    ZoneOverrideRequest,
    ZoneOverrideResponse,
)

INCHES_PER_METER = 39.3700787
FULL_FRAME_DIAGONAL_MM = math.hypot(36.0, 24.0)  # 43.266615 mm
DEFAULT_SMARTPHONE_FOCAL_35MM = 26.0
MAX_LONG_EDGE_PX = 1024

_STANDARDS_PATH = Path(__file__).resolve().parent / "anchor_standards.json"


@lru_cache(maxsize=1)
def load_anchor_standards() -> Dict[str, Dict[str, Any]]:
    """Load extensible Two-Tier Reference Anchor Registry from anchor_standards.json."""
    data = json.loads(_STANDARDS_PATH.read_text(encoding="utf-8"))
    return dict(data.get("standards") or {})


# --- Internal Structured Output Schemas for gemini-4-neon Vision ---


class _VisionAnchorRaw(BaseModel):
    anchor_id: str = Field(description="Short ID like 'A1', 'A2'")
    standard_key: Optional[str] = Field(
        default=None,
        description="Exact key from standards registry if matched (e.g. 'us_wall_outlet_plate', 'us_multigang_switch_plate', 'us_interior_door', 'kitchen_counter_height', 'modern_baseboard'), or null for a dynamic everyday object.",
    )
    label: str = Field(description="Concise label, e.g. 'US Wall Outlet', '27\" Desktop Monitor', 'Interior Door'")
    tier: AnchorTier = Field(
        default="code_invariant",
        description="code_invariant, manufactured_standard, dynamic_object, or architectural_variable",
    )
    y_min: float = Field(..., ge=0.0, le=1000.0)
    x_min: float = Field(..., ge=0.0, le=1000.0)
    y_max: float = Field(..., ge=0.0, le=1000.0)
    x_max: float = Field(..., ge=0.0, le=1000.0)
    measured_axis: Literal["height", "width"] = Field(
        default="height",
        description="Which bounding-box axis corresponds to the known physical dimension (always 'height' for wall plates/doors/counters/desks).",
    )
    known_inches: float = Field(
        ...,
        gt=0.5,
        description="Known physical size in inches along measured_axis.",
    )
    confidence_weight: float = Field(default=0.85, ge=0.1, le=1.0)
    plane_alignment: Literal["same_plane", "adjacent_wall", "foreground", "background"] = "same_plane"
    nearest_zone_id: Optional[str] = None


class _VisionProtectedRaw(BaseModel):
    protected_id: str = Field(description="Short ID like 'P1'")
    label: str = Field(description="Label of existing furniture to keep, e.g. 'Existing Standing Desk'")
    category: str = Field(default="desk")
    y_min: float = Field(..., ge=0.0, le=1000.0)
    x_min: float = Field(..., ge=0.0, le=1000.0)
    y_max: float = Field(..., ge=0.0, le=1000.0)
    x_max: float = Field(..., ge=0.0, le=1000.0)
    supports_surface_items: bool = True
    zone_id: Optional[str] = "Z1"


class _VisionZoneRaw(BaseModel):
    zone_id: str = Field(description="Numbered zone ID: 'Z1', 'Z2', 'Z3'")
    label: str = Field(description="Architectural label, e.g. 'Alcove Desk Gap', 'Sofa Wall', 'Center Rug & Table'")
    enclosure_type: EnclosureType = Field(
        default="enclosed_alcove",
        description="enclosed_alcove (between two walls/obstacles), corner_nook, open_wall, floor_island, existing_surface, or wall_vertical",
    )
    target_categories: List[str] = Field(default_factory=list)
    y_min: float = Field(..., ge=0.0, le=1000.0)
    x_min: float = Field(..., ge=0.0, le=1000.0)
    y_max: float = Field(..., ge=0.0, le=1000.0)
    x_max: float = Field(..., ge=0.0, le=1000.0)
    depth_to_width_ratio: float = Field(
        default=0.75,
        ge=0.2,
        le=3.0,
        description="Estimated physical floor depth divided by horizontal zone width based on room floor perspective.",
    )
    lateral_margin_in: float = Field(
        default=2.0,
        ge=0.0,
        le=6.0,
        description="2.0 for enclosed_alcove/corner_nook, 1.0 for open_wall, 0.0 for existing_surface/floor_island/wall_vertical.",
    )
    clearance_type: ClearanceType = Field(
        default="chair_pullout",
        description="chair_pullout (24 in), walkway (24 in), door_swing (30 in), sofa_legroom (16 in), bed_access (24 in), or none (0 in for shelves/lamps/art/rugs).",
    )
    functional_clearance_in: float = Field(
        default=24.0,
        ge=0.0,
        le=42.0,
    )
    estimated_camera_distance_m: float = Field(
        default=2.6,
        ge=0.6,
        le=12.0,
        description="Optical estimate of distance in meters from camera lens to the center of this zone (used only if both Layer 1 anchors and Depth-Anything-V2 weights are unavailable).",
    )


class _VisionSceneAudit(BaseModel):
    resolved_scope: ResolvedScope
    zones: List[_VisionZoneRaw]
    anchors: List[_VisionAnchorRaw] = Field(default_factory=list)
    protected_anchors: List[_VisionProtectedRaw] = Field(default_factory=list)


# --- Image & EXIF Utilities ---


def preprocess_room_image(
    image_input: Union[bytes, str, Path, Image.Image],
    max_long_edge: int = MAX_LONG_EDGE_PX,
) -> Tuple[Image.Image, bytes, Optional[float]]:
    """Extract EXIF 35mm focal length and downsize oversized photos to <=1024px JPEG."""
    exif_focal_35mm: Optional[float] = None

    if isinstance(image_input, Image.Image):
        pil_img = image_input
    else:
        if isinstance(image_input, (str, Path)):
            raw_bytes = Path(image_input).read_bytes()
        else:
            raw_bytes = image_input
        pil_img = Image.open(io.BytesIO(raw_bytes))

    # Extract EXIF FocalLengthIn35mmFilm (tag 41989) before resizing strips EXIF
    try:
        exif_data = pil_img.getexif()
        if exif_data:
            # Check top-level and Exif IFD (0x8769)
            tag_35mm = 41989
            if tag_35mm in exif_data and exif_data[tag_35mm]:
                exif_focal_35mm = float(exif_data[tag_35mm])
            else:
                exif_ifd = exif_data.get_ifd(0x8769) if hasattr(exif_data, "get_ifd") else {}
                if tag_35mm in exif_ifd and exif_ifd[tag_35mm]:
                    exif_focal_35mm = float(exif_ifd[tag_35mm])
    except Exception:
        exif_focal_35mm = None

    pil_img = pil_img.convert("RGB")
    w, h = pil_img.size
    long_edge = max(w, h)
    if long_edge > max_long_edge:
        scale = max_long_edge / float(long_edge)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=90)
    return pil_img, buf.getvalue(), exif_focal_35mm


def compute_focal_px_from_35mm(focal_35mm: float, img_w: int, img_h: int) -> float:
    """Rotation-invariant conversion of 35mm-equivalent focal length to pixel focal length `f_px`.

    Uses the exact 35mm full-frame diagonal (43.2666 mm), which stays invariant across
    4:3 smartphone photos, 3:2 DSLRs, and portrait/landscape rotations.
    """
    img_diag_px = math.hypot(float(img_w), float(img_h))
    return (float(focal_35mm) / FULL_FRAME_DIAGONAL_MM) * img_diag_px


# --- Optional Local Depth-Anything-V2 Metric Engine (Layer 2) ---

_DEPTH_PIPELINE_CACHE: Any = False  # False = uninitialized, None = unavailable


def _get_depth_anything_pipeline() -> Any:
    """Lazy-load Depth-Anything-V2-Metric-Indoor-Small-hf if local weights/transformers exist."""
    global _DEPTH_PIPELINE_CACHE
    if _DEPTH_PIPELINE_CACHE is not False:
        return _DEPTH_PIPELINE_CACHE

    # Respect 2:00 PM Scope Cut protection: only download HF weights if cached or explicitly enabled
    allow_download = os.getenv("CLEARBUY_ENABLE_DEPTH_DOWNLOAD", "0").lower() in ("1", "true", "yes")
    hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
    has_cached = any(
        "depth-anything-v2-metric-indoor" in p.name.lower()
        for p in (hf_cache.iterdir() if hf_cache.exists() else [])
    )
    if not has_cached and not allow_download:
        _DEPTH_PIPELINE_CACHE = None
        return None

    try:
        import torch  # type: ignore
        from transformers import pipeline  # type: ignore

        device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
        _DEPTH_PIPELINE_CACHE = pipeline(
            task="depth-estimation",
            model="depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf",
            device=device,
            local_files_only=not allow_download,
        )
    except Exception:
        _DEPTH_PIPELINE_CACHE = None
    return _DEPTH_PIPELINE_CACHE


def estimate_full_depth_map(pil_img: Image.Image) -> Tuple[Optional[np.ndarray], str]:
    """Run Depth-Anything-V2-Metric-Indoor-Small once per image and return `(depth_map_m, engine_name)`."""
    pipe = _get_depth_anything_pipeline()
    if pipe is not None:
        try:
            out = pipe(pil_img)
            pred = out.get("predicted_depth")
            if pred is not None:
                arr = pred.detach().cpu().numpy() if hasattr(pred, "detach") else np.asarray(pred)
                return np.squeeze(arr).astype(np.float32), "Depth-Anything-V2-Metric-Indoor-Small"
        except Exception:
            pass
    return None, "gemini-4-neon-optical-depth"


def median_depth_in_bbox(
    depth_arr: np.ndarray,
    img_w: int,
    img_h: int,
    bbox_px: BBoxPx,
) -> Optional[float]:
    """Extract median metric depth (meters) inside a pixel bounding box from a precomputed depth map."""
    dh, dw = depth_arr.shape[:2]
    x1 = max(0, min(dw - 1, int(round((bbox_px.x1 / img_w) * dw))))
    x2 = max(x1 + 1, min(dw, int(round((bbox_px.x2 / img_w) * dw))))
    y1 = max(0, min(dh - 1, int(round((bbox_px.y1 / img_h) * dh))))
    y2 = max(y1 + 1, min(dh, int(round((bbox_px.y2 / img_h) * dh))))
    patch = depth_arr[y1:y2, x1:x2]
    valid = patch[np.isfinite(patch) & (patch > 0.25) & (patch < 20.0)]
    if valid.size == 0:
        return None
    return float(np.median(valid))


def estimate_zone_metric_depth_m(
    pil_img: Image.Image,
    zone_bbox_px: BBoxPx,
    optical_fallback_m: float = 2.6,
) -> Tuple[float, str]:
    """Return `(median_depth_meters, engine_name)` inside `zone_bbox_px`."""
    arr, eng = estimate_full_depth_map(pil_img)
    if arr is not None:
        iw, ih = pil_img.size
        med = median_depth_in_bbox(arr, iw, ih, zone_bbox_px)
        if med is not None:
            return med, eng
    return float(optical_fallback_m), "gemini-4-neon-optical-depth"


# --- Deterministic Anchor Resolution & Cross-Anchor Skew Math ---


def _resolve_detected_anchors(
    raw_anchors: Sequence[_VisionAnchorRaw],
    img_w: int,
    img_h: int,
) -> List[DetectedAnchor]:
    """Convert raw vision detections into pixel-calibrated anchors using `anchor_standards.json`."""
    standards = load_anchor_standards()
    resolved: List[DetectedAnchor] = []

    for idx, raw in enumerate(raw_anchors):
        bbox_1000 = BBox1000(
            y_min=raw.y_min,
            x_min=raw.x_min,
            y_max=raw.y_max,
            x_max=raw.x_max,
        )
        bbox_px = bbox_1000.to_px(img_w, img_h)

        std_entry = standards.get(raw.standard_key or "") if raw.standard_key else None
        if std_entry is not None:
            tier: AnchorTier = std_entry.get("tier", raw.tier)
            preferred_axis = std_entry.get("preferred_axis") or raw.measured_axis
            axis: Literal["height", "width"] = "height" if preferred_axis == "height" else "width"
            known_in = std_entry.get("height_in") if axis == "height" else std_entry.get("width_in")
            if known_in is None:
                axis = "height" if std_entry.get("height_in") is not None else "width"
                known_in = std_entry.get("height_in") or std_entry.get("width_in") or raw.known_inches
            conf_weight = float(std_entry.get("confidence_weight", raw.confidence_weight))
            label = raw.label or str(std_entry.get("display_name") or raw.standard_key)
        else:
            tier = raw.tier if raw.tier != "code_invariant" else "dynamic_object"
            axis = raw.measured_axis
            known_in = float(raw.known_inches)
            # Cap dynamic non-registry objects at 0.78 confidence weight
            conf_weight = min(0.78, float(raw.confidence_weight))
            label = raw.label

        # Down-weight baseboard or flat/tray/floor items that suffer perspective tilt foreshortening
        lower_lbl = label.lower()
        if any(kw in lower_lbl for kw in ("baseboard", "molding", "tray", "paper", "rug", "floor tile")):
            tier = "architectural_variable"
            conf_weight = min(conf_weight, 0.40)

        axis_px = bbox_px.height_px if axis == "height" else bbox_px.width_px
        if axis_px < 6.0 or known_in <= 0.0:
            # Skip sub-6px noisy detections
            continue

        px_per_in = round(axis_px / float(known_in), 3)
        if px_per_in <= 0.2 or px_per_in > 180.0:
            continue

        axis_short = "H" if axis == "height" else "W"
        callout = f"{label} · {float(known_in):g}\" {axis_short} -> {px_per_in:.1f} px/in"

        resolved.append(
            DetectedAnchor(
                anchor_id=raw.anchor_id or f"A{idx + 1}",
                standard_key=raw.standard_key if std_entry else None,
                label=label,
                tier=tier,
                bbox_1000=bbox_1000,
                bbox_px=bbox_px,
                measured_axis=axis,
                known_inches=round(float(known_in), 2),
                axis_pixels=round(axis_px, 2),
                px_per_inch=px_per_in,
                confidence_weight=round(conf_weight, 2),
                plane_alignment=raw.plane_alignment,
                nearest_zone_id=raw.nearest_zone_id,
                callout_text=callout,
            )
        )
    return resolved


def compute_multi_anchor_audit(
    anchors: Sequence[DetectedAnchor],
) -> Tuple[Optional[DetectedAnchor], Optional[float], float, bool]:
    """Run Weighted Cross-Anchor Consistency Audit (Frontier Upgrade 3).

    Returns `(primary_anchor, consensus_px_per_in, cross_anchor_skew_pct, foreshortening_flagged)`.
    """
    if not anchors:
        return None, None, 0.0, False

    # Prefer same_plane Tier 1A/1B anchors over variable baseboards or foreground/background objects
    strong_anchors = [
        a for a in anchors
        if a.tier != "architectural_variable" and a.plane_alignment in ("same_plane", "adjacent_wall")
    ]
    pool = strong_anchors if strong_anchors else list(anchors)

    # Sort by (same_plane bonus, confidence_weight, axis_pixels)
    ranked = sorted(
        pool,
        key=lambda a: (
            1 if a.plane_alignment == "same_plane" else 0,
            a.confidence_weight,
            min(a.axis_pixels, 250.0) / 250.0,
        ),
        reverse=True,
    )
    primary = ranked[0]

    # Compute cross-anchor skew across same_plane reliable anchors
    audit_pool = [a for a in pool if a.plane_alignment == "same_plane"]
    if len(audit_pool) < 2:
        audit_pool = pool

    if len(audit_pool) >= 2:
        rates = [a.px_per_inch for a in audit_pool]
        median_rate = statistics.median(rates)
        max_dev = max(abs(r - median_rate) for r in rates)
        skew_pct = round((max_dev / median_rate) * 100.0, 1) if median_rate > 0 else 0.0
    else:
        skew_pct = 0.0

    foreshortening_flagged = skew_pct > 15.0

    # Weighted average px/in when consistent; otherwise lock onto top-ranked co-planar anchor
    if not foreshortening_flagged and len(audit_pool) >= 2:
        w_sum = sum(a.confidence_weight for a in audit_pool)
        consensus = round(
            sum(a.px_per_inch * a.confidence_weight for a in audit_pool) / w_sum,
            3,
        )
    else:
        consensus = primary.px_per_inch

    return primary, consensus, skew_pct, foreshortening_flagged


# --- Main Scale Calibration Entrypoints ---


def _build_vision_prompt(user_prompt: str, scope: ScopeMode) -> str:
    standards = load_anchor_standards()
    registry_lines = [
        f"- `{key}`: {meta['display_name']} ("
        + (f"H={meta['height_in']}\"" if meta.get("height_in") else "")
        + (", " if meta.get("height_in") and meta.get("width_in") else "")
        + (f"W={meta['width_in']}\"" if meta.get("width_in") else "")
        + f", preferred_axis='{meta['preferred_axis']}', tier='{meta['tier']}')"
        for key, meta in standards.items()
    ]
    registry_block = "\n".join(registry_lines)

    return (
        "You are ClearBuy's Architectural Spatial Metrology Vision Engine.\n"
        "Analyze this room photograph and the user's furnishing request to return exact 0-1000 normalized "
        "2D bounding boxes (`y_min`, `x_min`, `y_max`, `x_max`) for:\n"
        "1. `resolved_scope`: 'nook' (single gap/corner/wall stretch), 'upgrade' (keeping existing main furniture "
        "and replacing/adding items around or on it), or 'full_room' (2+ distinct spatial zones).\n"
        f"   (User requested scope hint: '{scope}'.)\n"
        "2. `zones`: Every target placement zone (`Z1`, `Z2`, ...) matching the user's request. For each zone:\n"
        "   - Set `enclosure_type` accurately (`enclosed_alcove`, `corner_nook`, `open_wall`, `floor_island`, `existing_surface`, `wall_vertical`).\n"
        "   - Set context-appropriate `lateral_margin_in` (`2.0` when bounded between walls/furniture, `1.0` open wall, `0.0` existing_surface/rug/wall art).\n"
        "   - Set context-appropriate `clearance_type` & `functional_clearance_in` (`24.0` for desk/dining chair pull-out or room walkways, `30.0` door swing, `16.0` sofa-to-coffee-table legroom, `0.0` for flush bookcases, lamps, rugs, wall art, or tabletop upgrades).\n"
        "   - Estimate `depth_to_width_ratio` and `estimated_camera_distance_m` from room perspective.\n"
        "3. `anchors`: Detect EVERY visible physical reference object in the room for deterministic pixel-to-inch scale calibration!\n"
        "   - First check known standards:\n"
        f"{registry_block}\n"
        "   - ALSO detect ANY other recognizable manufactured/everyday object visible in the photo "
        "(e.g., laptop, monitor, kitchen appliance, folding chair, soda can, standard tile, brick, window frame) "
        "with `standard_key: null`, `tier: 'dynamic_object'`, accurate bounding box, `measured_axis`, and `known_inches`.\n"
        "   - For multi-gang wall switch plates, ALWAYS measure `height` (`4.5` in), never width!\n"
        "   - Tag `plane_alignment` ('same_plane' if at the same wall/depth as the target zone).\n"
        "4. `protected_anchors`: If `resolved_scope == 'upgrade'` (user wants to keep existing furniture like their current desk/sofa/bed), "
        "return tight bounding boxes around every kept item.\n\n"
        f"USER SPOKEN REQUEST: {user_prompt!r}"
    )


def calibrate_space_sync(
    image_input: Union[bytes, str, Path, Image.Image],
    prompt: str,
    scope: ScopeMode = "auto",
    exif_focal_mm: Optional[float] = None,
    thinking_level: str = "medium",
    angle_index: int = 0,
    zone_id_offset: int = 0,
    model: str = MODEL_NEON,
) -> ScaleCalibrationResult:
    """Run Two-Layer Zero-Measurement Scale Calibration on a single room angle."""
    t0 = time.perf_counter()
    assert_supported_model(model)

    pil_img, jpeg_bytes, extracted_exif_mm = preprocess_room_image(image_input)
    img_w, img_h = pil_img.size

    effective_focal_mm = exif_focal_mm or extracted_exif_mm
    exif_assumed_default = False
    if effective_focal_mm is None or effective_focal_mm <= 0:
        effective_focal_mm = DEFAULT_SMARTPHONE_FOCAL_35MM
        exif_assumed_default = True
    f_px = round(compute_focal_px_from_35mm(effective_focal_mm, img_w, img_h), 2)

    client = get_genai_client(api_version="v1beta")
    b64_img = base64.b64encode(jpeg_bytes).decode("ascii")
    vision_prompt = _build_vision_prompt(prompt, scope)

    # Call gemini-4-neon with requested thinking_level (with automatic fallback from xhigh->high if needed)
    audit_raw: Optional[_VisionSceneAudit] = None
    used_thinking = thinking_level
    for candidate_tl in ([thinking_level, "high"] if thinking_level == "xhigh" else [thinking_level]):
        try:
            interaction = client.interactions.create(
                model=model,
                input=[
                    {"type": "image", "data": b64_img, "mime_type": "image/jpeg"},
                    {"type": "text", "text": vision_prompt},
                ],
                generation_config={"thinking_level": candidate_tl},
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": _VisionSceneAudit.model_json_schema(),
                },
            )
            audit_raw = _VisionSceneAudit.model_validate_json(interaction.output_text)
            used_thinking = candidate_tl
            break
        except Exception as exc:
            if candidate_tl == "xhigh" and "thinking" in str(exc).lower():
                continue
            raise

    assert audit_raw is not None
    resolved_scope: ResolvedScope = (
        scope if scope in ("nook", "upgrade", "full_room") else audit_raw.resolved_scope  # type: ignore[assignment]
    )

    anchors = _resolve_detected_anchors(audit_raw.anchors, img_w, img_h)
    primary_anchor, consensus_px_per_in, skew_pct, foreshortened = compute_multi_anchor_audit(anchors)

    # Use Layer 1 if we have at least one non-variable anchor; if ONLY a baseboard exists, fuse/corroborate with Layer 2!
    has_solid_layer1 = (
        primary_anchor is not None
        and consensus_px_per_in is not None
        and primary_anchor.tier != "architectural_variable"
    )

    protected_models: List[ProtectedAnchor] = []
    for idx, p_raw in enumerate(audit_raw.protected_anchors):
        pb1000 = BBox1000(y_min=p_raw.y_min, x_min=p_raw.x_min, y_max=p_raw.y_max, x_max=p_raw.x_max)
        pbpx = pb1000.to_px(img_w, img_h)
        est_w = round(pbpx.width_px / consensus_px_per_in, 1) if consensus_px_per_in else None
        est_d = round(est_w * 0.55, 1) if est_w else None
        protected_models.append(
            ProtectedAnchor(
                protected_id=p_raw.protected_id or f"P{idx + 1}",
                label=p_raw.label,
                category=p_raw.category,
                bbox_1000=pb1000,
                bbox_px=pbpx,
                estimated_width_in=est_w,
                estimated_depth_in=est_d,
                supports_surface_items=p_raw.supports_surface_items,
                zone_id=p_raw.zone_id,
            )
        )

    # Guarantee at least 1 target zone even if vision returned empty list
    raw_zones = audit_raw.zones or [
        _VisionZoneRaw(
            zone_id="Z1",
            label="Primary Room Zone",
            enclosure_type="enclosed_alcove",
            target_categories=["furniture"],
            y_min=250.0,
            x_min=180.0,
            y_max=850.0,
            x_max=820.0,
        )
    ]

    zones: List[SpatialZone] = []
    median_depths: List[float] = []
    # Compute Depth-Anything-V2 map once (~0.35s on MPS) to cross-verify anchor plane depth & power Layer 2
    full_depth_map, detected_depth_eng = estimate_full_depth_map(pil_img)
    depth_engine_used: Optional[str] = detected_depth_eng if full_depth_map is not None else None
    calibration_layer: Literal[1, 2] = 1 if has_solid_layer1 else 2

    for idx, z_raw in enumerate(raw_zones):
        z_num = zone_id_offset + idx + 1
        zone_id = f"Z{z_num}"
        zb1000 = BBox1000(y_min=z_raw.y_min, x_min=z_raw.x_min, y_max=z_raw.y_max, x_max=z_raw.x_max)
        zbpx = zb1000.to_px(img_w, img_h)

        z_depth_m: Optional[float] = (
            median_depth_in_bbox(full_depth_map, img_w, img_h, zbpx)
            if full_depth_map is not None
            else None
        )
        if z_depth_m is not None:
            median_depths.append(z_depth_m)

        if has_solid_layer1 and consensus_px_per_in is not None and primary_anchor is not None:
            zone_anchor = next(
                (
                    a for a in anchors
                    if a.nearest_zone_id == z_raw.zone_id
                    and a.tier != "architectural_variable"
                    and a.plane_alignment == "same_plane"
                ),
                primary_anchor,
            )
            active_rate = zone_anchor.px_per_inch if foreshortened else consensus_px_per_in
            anchor_w_in = zbpx.width_px / active_rate
            ref_anchor_id: Optional[str] = zone_anchor.anchor_id

            # 3D Depth-Ratio Plane Correction & Tilted-Anchor Outlier Rejection:
            # Scale shifts linearly with depth Z (`W_zone = (zone_px / anchor_px_per_in) * (Z_zone / Z_anchor)`).
            # Note: any global scale factor in Depth-Anything-V2 cancels out in `Z_zone / Z_anchor`!
            if full_depth_map is not None and z_depth_m is not None:
                a_depth_m = median_depth_in_bbox(full_depth_map, img_w, img_h, zone_anchor.bbox_px)
                if a_depth_m is not None and a_depth_m > 0.3:
                    depth_ratio = max(0.55, min(1.85, z_depth_m / a_depth_m))
                    if abs(depth_ratio - 1.0) > 0.12:
                        anchor_w_in = anchor_w_in * depth_ratio

                pinhole_w_in = ((zbpx.width_px * z_depth_m) / f_px) * INCHES_PER_METER
                rel_diff = abs(anchor_w_in - pinhole_w_in) / max(pinhole_w_in, 12.0)

                if rel_diff > 0.35 and (
                    foreshortened
                    or zone_anchor.axis_pixels < 28.0
                    or zone_anchor.tier != "code_invariant"
                ):
                    # Anchor is severely foreshortened/tilted or tiny -> fall back cleanly to Layer 2 Depth+EXIF!
                    width_in = round(max(12.0, pinhole_w_in), 1)
                    z_layer: Literal[1, 2] = 2
                    z_uncertainty = 3.8
                    z_conf: Literal["high", "medium", "low"] = "medium"
                    ref_anchor_id = None
                    if idx == 0:
                        calibration_layer = 2
                elif foreshortened or zone_anchor.axis_pixels < 28.0:
                    width_in = round(max(12.0, 0.50 * anchor_w_in + 0.50 * pinhole_w_in), 1)
                    z_layer = 1
                    z_uncertainty = 2.2
                    z_conf = "medium"
                else:
                    width_in = round(max(12.0, anchor_w_in), 1)
                    z_layer = 1
                    z_uncertainty = 1.5 if zone_anchor.tier == "code_invariant" else 2.2
                    z_conf = "high" if zone_anchor.tier == "code_invariant" else "medium"
            else:
                width_in = round(max(12.0, anchor_w_in), 1)
                z_layer = 1
                z_uncertainty = 1.5 if (zone_anchor.tier == "code_invariant" and not foreshortened) else 2.2
                z_conf = "high" if (zone_anchor.tier == "code_invariant" and not foreshortened) else "medium"
        else:
            # Layer 2: Automatic Metric Depth + Camera EXIF Pinhole Math
            if z_depth_m is None:
                z_depth_m = float(z_raw.estimated_camera_distance_m)
                depth_engine_used = "gemini-4-neon-optical-depth"
                median_depths.append(z_depth_m)
            zone_width_m = (zbpx.width_px * z_depth_m) / f_px
            pinhole_w_in = zone_width_m * INCHES_PER_METER

            if primary_anchor is not None and primary_anchor.tier == "architectural_variable":
                bb_w_in = zbpx.width_px / primary_anchor.px_per_inch
                if abs(bb_w_in - pinhole_w_in) / max(pinhole_w_in, 12.0) <= 0.25:
                    width_in = round(max(12.0, 0.70 * pinhole_w_in + 0.30 * bb_w_in), 1)
                    ref_anchor_id = primary_anchor.anchor_id
                else:
                    width_in = round(max(12.0, pinhole_w_in), 1)
                    ref_anchor_id = None
            else:
                width_in = round(max(12.0, pinhole_w_in), 1)
                ref_anchor_id = None

            z_uncertainty = 3.8 if depth_engine_used == "Depth-Anything-V2-Metric-Indoor-Small" else 4.2
            z_conf = "medium" if not exif_assumed_default else "low"
            z_layer = 2

        depth_in = round(max(14.0, width_in * z_raw.depth_to_width_ratio), 1)
        # Ensure realistic room depth if chair pullout or walkway applies
        if z_raw.functional_clearance_in >= 24.0 and depth_in < 48.0 and z_raw.enclosure_type != "existing_surface":
            depth_in = max(depth_in, 54.0)

        lat_margin = round(float(z_raw.lateral_margin_in), 1)
        usable_w = round(max(6.0, width_in - lat_margin), 1)

        zones.append(
            SpatialZone(
                zone_id=zone_id,
                angle_index=angle_index,
                label=z_raw.label,
                enclosure_type=z_raw.enclosure_type,
                target_categories=z_raw.target_categories,
                bbox_1000=zb1000,
                bbox_px=zbpx,
                width_in=width_in,
                depth_in=depth_in,
                lateral_margin_in=lat_margin,
                usable_width_in=usable_w,
                clearance_type=z_raw.clearance_type,
                functional_clearance_in=round(float(z_raw.functional_clearance_in), 1),
                calibration_layer=z_layer,
                reference_anchor_id=ref_anchor_id,
                uncertainty_in=z_uncertainty,
                confidence_band=z_conf,
            )
        )

    overall_uncertainty = max((z.uncertainty_in for z in zones), default=1.5)
    overall_conf: Literal["high", "medium", "low"] = (
        "high"
        if calibration_layer == 1 and not foreshortened and primary_anchor and primary_anchor.tier == "code_invariant"
        else ("medium" if calibration_layer == 1 or depth_engine_used == "Depth-Anything-V2-Metric-Indoor-Small" else "low")
    )

    if calibration_layer == 1 and primary_anchor is not None:
        skew_suffix = f" · Skew {skew_pct:.0f}% (Foreshortened)" if foreshortened else ""
        badge_label = f"{primary_anchor.callout_text} (±{overall_uncertainty:.1f}\"){skew_suffix}"
    else:
        exif_tag = f"EXIF {effective_focal_mm:g}mm" + (" (est)" if exif_assumed_default else "")
        eng_label = "Depth-Anything-V2" if depth_engine_used == "Depth-Anything-V2-Metric-Indoor-Small" else "Optical Pinhole"
        badge_label = f"No code anchor · Calibrated via {eng_label} + {exif_tag} (±{overall_uncertainty:.1f}\")"

    latency_ms = int((time.perf_counter() - t0) * 1000)

    return ScaleCalibrationResult(
        scope=resolved_scope,
        calibration_layer=calibration_layer,
        primary_anchor=primary_anchor,
        all_anchors=anchors,
        protected_anchors=protected_models,
        zones=zones,
        px_per_inch=consensus_px_per_in if calibration_layer == 1 else None,
        cross_anchor_skew_pct=skew_pct,
        foreshortening_flagged=foreshortened,
        exif_focal_mm=effective_focal_mm,
        exif_assumed_default=exif_assumed_default,
        exif_fx_px=f_px,
        median_depth_m=round(statistics.median(median_depths), 2) if median_depths else None,
        depth_engine_used=depth_engine_used,
        uncertainty_in=overall_uncertainty,
        confidence_band=overall_conf,
        badge_label=badge_label,
        thinking_level=used_thinking,
        image_width_px=img_w,
        image_height_px=img_h,
        latency_ms=latency_ms,
    )


def to_scale_ready_event(
    cal: ScaleCalibrationResult,
    session_id: str,
    prompt: str = "",
) -> ScaleReadyEvent:
    """Convert the internal `ScaleCalibrationResult` into the SSE `ScaleReadyEvent`."""
    from backend.adapters import extract_requested_categories

    req_cats = extract_requested_categories(prompt, scope=cal.scope) if prompt else []

    def _map_anchor_type(a: DetectedAnchor) -> Literal["outlet", "door", "desk", "baseboard", "other"]:
        lbl = f"{a.standard_key or ''} {a.label}".lower()
        if "outlet" in lbl or "switch" in lbl or "socket" in lbl:
            return "outlet"
        if "door" in lbl:
            return "door"
        if "desk" in lbl or "counter" in lbl:
            return "desk"
        if "baseboard" in lbl:
            return "baseboard"
        return "other"

    def _to_ref(a: DetectedAnchor) -> ApiReferenceAnchor:
        return ApiReferenceAnchor(
            anchor_id=a.anchor_id,
            label=f'{a.label} · {a.known_inches:g}" {"H" if a.measured_axis == "height" else "W"}',
            anchor_type=_map_anchor_type(a),
            known_inches=a.known_inches,
            measured_axis=a.measured_axis,
            px_per_in=round(a.px_per_inch, 2),
            bbox=BoundingBox(
                y_min=a.bbox_1000.y_min,
                x_min=a.bbox_1000.x_min,
                y_max=a.bbox_1000.y_max,
                x_max=a.bbox_1000.x_max,
            ),
        )

    api_anchors = [_to_ref(a) for a in cal.all_anchors]
    api_primary = _to_ref(cal.primary_anchor) if cal.primary_anchor else None

    api_zones: List[ApiSpatialZone] = []
    for idx, z in enumerate(cal.zones):
        # Ensure canonical categories match ShopMCPClient pools (`desk`, `chair`, `shelf`, `sofa`, `coffee table`, `lamp`, `rug`, `desk mat`)
        zcats = [c.lower() for c in z.target_categories]
        if len(cal.zones) == 1 and req_cats:
            zcats = req_cats
        elif not zcats and req_cats:
            zcats = [req_cats[idx % len(req_cats)]]

        api_zones.append(
            ApiSpatialZone(
                zone_id=f"zone_{idx + 1}",
                label=f"Zone {idx + 1} · {z.label}" if not z.label.lower().startswith("zone") else z.label,
                target_categories=zcats,
                bbox=BoundingBox(
                    y_min=z.bbox_1000.y_min,
                    x_min=z.bbox_1000.x_min,
                    y_max=z.bbox_1000.y_max,
                    x_max=z.bbox_1000.x_max,
                ),
                width_in=z.width_in,
                depth_in=z.depth_in,
                clearance_required_in=z.functional_clearance_in,
                wall_margin_in=z.lateral_margin_in,
                usable_width_in=z.usable_width_in,
                confidence_tier=z.confidence_band,
                tolerance_in=z.uncertainty_in,
                overridden_by_user=z.override_applied,
            )
        )

    api_protected = [
        ApiProtectedAnchor(
            label=p.label,
            bbox=BoundingBox(
                y_min=p.bbox_1000.y_min,
                x_min=p.bbox_1000.x_min,
                y_max=p.bbox_1000.y_max,
                x_max=p.bbox_1000.x_max,
            ),
        )
        for p in cal.protected_anchors
    ]

    fallback_badge: Optional[str] = None
    if cal.calibration_layer == 2:
        fallback_badge = cal.badge_label
    elif cal.foreshortening_flagged:
        fallback_badge = f'Anchor skew {cal.cross_anchor_skew_pct:.1f}% (>15% foreshortening) · ±{cal.uncertainty_in:.1f}"'

    return ScaleReadyEvent(
        session_id=session_id,
        detected_scope=cal.scope,
        calibration_layer=cal.calibration_layer,
        calibration_summary=cal.badge_label,
        fallback_badge=fallback_badge,
        primary_anchor=api_primary,
        anchors_detected=api_anchors,
        cross_anchor_skew_pct=cal.cross_anchor_skew_pct,
        foreshortening_warning=cal.foreshortening_flagged,
        zones=api_zones,
        protected_anchors=api_protected,
        elapsed_ms=cal.latency_ms,
    )


async def calibrate_space(
    image_input: Optional[Union[bytes, str, Path, Image.Image]] = None,
    prompt: str = "",
    scope: ScopeMode = "auto",
    exif_focal_mm: Optional[float] = None,
    thinking_level: str = "medium",
    angle_index: int = 0,
    zone_id_offset: int = 0,
    model: str = MODEL_NEON,
    *,
    session_id: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
) -> Any:
    """Async entrypoint supporting BOTH the internal `ScaleCalibrationResult` and the SSE `ScaleReadyEvent`."""
    resolved_img = image_input if image_input is not None else image_bytes
    if resolved_img is None:
        raise ValueError("Either image_input or image_bytes is required.")

    if session_id is not None and not _backend_config.has_live_gemini_credentials():
        # Allow offline unit tests to fall through to deterministic fixture
        raise RuntimeError("No live Gemini credentials; delegate to offline adapter fixture.")

    cal = await asyncio.to_thread(
        calibrate_space_sync,
        resolved_img,
        prompt,
        scope,
        exif_focal_mm,
        thinking_level,
        angle_index,
        zone_id_offset,
        model,
    )
    if session_id is not None:
        return to_scale_ready_event(cal, session_id=session_id, prompt=prompt)
    return cal


async def calibrate_workspace(
    images: Sequence[Union[bytes, str, Path, Image.Image]],
    prompt: str,
    scope: ScopeMode = "auto",
    exif_focal_mm_list: Optional[Sequence[Optional[float]]] = None,
    thinking_level: str = "medium",
) -> List[ScaleCalibrationResult]:
    """Calibrate 1-3 room angles with unified sequential zone IDs (`Z1`, `Z2`, ...)."""
    results: List[ScaleCalibrationResult] = []
    zone_offset = 0
    for idx, img in enumerate(images[:3]):
        focal = (
            exif_focal_mm_list[idx]
            if exif_focal_mm_list and idx < len(exif_focal_mm_list)
            else None
        )
        res = await calibrate_space(
            image_input=img,
            prompt=prompt,
            scope=scope,
            exif_focal_mm=focal,
            thinking_level=thinking_level,
            angle_index=idx,
            zone_id_offset=zone_offset,
        )
        zone_offset += len(res.zones)
        results.append(res)
    return results


def recalculate_zone_override(
    calibration: ScaleCalibrationResult,
    override: ZoneOverrideRequest,
    current_items: Sequence[ProposedItem],
    budget_usd: float,
) -> ZoneOverrideResponse:
    """Instantaneous (<5 ms) recalculation for `PATCH /api/session/{id}/zone` measure drags."""
    target_zone: Optional[SpatialZone] = None
    for z in calibration.zones:
        if z.zone_id == override.zone_id:
            if override.override_width_in is not None:
                z.width_in = round(float(override.override_width_in), 1)
                z.usable_width_in = round(max(4.0, z.width_in - z.lateral_margin_in), 1)
            if override.override_depth_in is not None:
                z.depth_in = round(float(override.override_depth_in), 1)
            z.override_applied = True
            z.uncertainty_in = 0.5
            z.confidence_band = "high"
            target_zone = z
            break

    if target_zone is None:
        raise KeyError(f"Zone '{override.zone_id}' not found in session calibration.")

    constraints_dict = {
        "budget_usd": budget_usd,
        "zones": [z.model_dump() for z in calibration.zones],
        "protected_anchors": [p.model_dump() for p in calibration.protected_anchors],
        "require_shopify_gid": False,
        "allow_unverified_primary": True,
    }
    proposal_dict = {
        "budget_usd": budget_usd,
        "items": [it.model_dump() for it in current_items],
    }

    eval_raw = (
        verify_bundle_dict(proposal_dict, constraints_dict)
        if current_items
        else {
            "attempt": 1,
            "decision": "allow",
            "reason": f"Zone {target_zone.zone_id} updated to {target_zone.width_in:.1f}\" W x {target_zone.depth_in:.1f}\" D.",
            "total_usd": 0.0,
            "budget_usd": budget_usd,
            "violations": [],
            "zone_summaries": {},
            "timestamp_ms": int(time.time() * 1000),
        }
    )
    hook_event = HookTraceEvent.model_validate(eval_raw)

    violated_item_ids = {
        v.item_id for v in hook_event.violations if v.item_id
    }
    violated_zones = {
        v.zone_id for v in hook_event.violations if v.zone_id and v.code in ("ZONE_WIDTH_OVERFLOW", "DEPTH_CLEARANCE_VIOLATION", "WALKWAY_CLEARANCE_VIOLATION")
    }

    updated_items: List[ProposedItem] = []
    z_lookup = {z.zone_id: z for z in calibration.zones}
    for item in current_items:
        copy_item = item.model_copy(deep=True)
        z_ref = z_lookup.get(copy_item.zone_id)
        if copy_item.item_id in violated_item_ids or (
            copy_item.zone_id in violated_zones and copy_item.placement_mode == "floor_anchor"
        ):
            copy_item.fit_status = "blocked_by_hook"
            if z_ref and copy_item.width_in:
                copy_item.fit_badge_text = f"Blocked by Hook · {copy_item.width_in:.1f}\" > {z_ref.usable_width_in:.1f}\""
            else:
                copy_item.fit_badge_text = "Blocked by Hook"
        elif copy_item.dimensions_unverified or copy_item.width_in is None:
            copy_item.fit_status = "unverified_specs"
            copy_item.fit_badge_text = "Unverified Specs · Check Seller"
        else:
            copy_item.fit_status = "verified_fit"
            limit_w = z_ref.usable_width_in if (z_ref and copy_item.placement_mode == "floor_anchor") else (
                z_ref.width_in if z_ref else copy_item.width_in
            )
            copy_item.fit_badge_text = f"Verified Fit · {copy_item.width_in:.1f}\" <= {limit_w:.1f}\""
        updated_items.append(copy_item)

    return ZoneOverrideResponse(
        updated_zone=target_zone,
        hook_evaluation=hook_event,
        updated_items=updated_items,
    )


# --- Voice Audio Transcription Fallback & Video Walkthrough Stretch Goal ---


class _VideoWalkthroughAudit(_VisionSceneAudit):
    spoken_transcript: str = Field(
        default="",
        description="Verbatim spoken furnishing goal & budget extracted from the video's audio track.",
    )
    extracted_budget_usd: Optional[float] = Field(
        default=None,
        description="Numeric USD budget spoken in the walkthrough, if mentioned.",
    )


def transcribe_spoken_audio_sync(
    audio_bytes: bytes,
    mime_type: str = "audio/webm",
    model: str = MODEL_TRANSCRIBE,
) -> str:
    """Server-side speech-to-text fallback (gemini-3.5-transcribe) when browser Web Speech is unavailable."""
    client = get_genai_client(api_version="v1beta")
    b64_audio = base64.b64encode(audio_bytes).decode("ascii")
    interaction = client.interactions.create(
        model=model,
        input=[
            {"type": "audio", "data": b64_audio, "mime_type": mime_type},
            {"type": "text", "text": "Transcribe the user's spoken room furnishing request and dollar budget accurately."},
        ],
    )
    return (interaction.output_text or "").strip()


async def transcribe_spoken_audio(
    audio_bytes: bytes,
    mime_type: str = "audio/webm",
    model: str = MODEL_TRANSCRIBE,
) -> str:
    return await asyncio.to_thread(transcribe_spoken_audio_sync, audio_bytes, mime_type, model)


def calibrate_video_walkthrough_sync(
    video_bytes: bytes,
    mime_type: str = "video/mp4",
    fallback_prompt: str = "Furnish this space within budget.",
    frame_width_px: int = 1024,
    frame_height_px: int = 768,
    exif_focal_mm: float = DEFAULT_SMARTPHONE_FOCAL_35MM,
    thinking_level: str = "medium",
) -> Tuple[str, Optional[float], ScaleCalibrationResult]:
    """Frontier Upgrade 3 Stretch Goal: Native 5-8s smartphone video+audio walkthrough in one gemini-4-neon pass."""
    t0 = time.perf_counter()
    client = get_genai_client(api_version="v1beta")
    b64_vid = base64.b64encode(video_bytes).decode("ascii")
    prompt = (
        _build_vision_prompt(fallback_prompt, "auto")
        + "\n5. Also extract `spoken_transcript` and `extracted_budget_usd` directly from the walkthrough audio track."
    )
    interaction = client.interactions.create(
        model=MODEL_NEON,
        input=[
            {"type": "video", "data": b64_vid, "mime_type": mime_type},
            {"type": "text", "text": prompt},
        ],
        generation_config={"thinking_level": thinking_level},
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": _VideoWalkthroughAudit.model_json_schema(),
        },
    )
    parsed = _VideoWalkthroughAudit.model_validate_json(interaction.output_text)
    anchors = _resolve_detected_anchors(parsed.anchors, frame_width_px, frame_height_px)
    primary, consensus_rate, skew_pct, foreshortened = compute_multi_anchor_audit(anchors)
    f_px = round(compute_focal_px_from_35mm(exif_focal_mm, frame_width_px, frame_height_px), 2)

    zones: List[SpatialZone] = []
    for idx, z_raw in enumerate(parsed.zones or []):
        zb1000 = BBox1000(y_min=z_raw.y_min, x_min=z_raw.x_min, y_max=z_raw.y_max, x_max=z_raw.x_max)
        zbpx = zb1000.to_px(frame_width_px, frame_height_px)
        if consensus_rate and primary and primary.tier != "architectural_variable":
            w_in = round(max(12.0, zbpx.width_px / consensus_rate), 1)
            layer: Literal[1, 2] = 1
            unc = 1.8
        else:
            w_in = round(max(12.0, ((zbpx.width_px * z_raw.estimated_camera_distance_m) / f_px) * INCHES_PER_METER), 1)
            layer = 2
            unc = 3.8
        d_in = round(max(18.0, w_in * z_raw.depth_to_width_ratio), 1)
        zones.append(
            SpatialZone(
                zone_id=f"Z{idx + 1}",
                label=z_raw.label,
                enclosure_type=z_raw.enclosure_type,
                target_categories=z_raw.target_categories,
                bbox_1000=zb1000,
                bbox_px=zbpx,
                width_in=w_in,
                depth_in=d_in,
                lateral_margin_in=z_raw.lateral_margin_in,
                usable_width_in=round(max(6.0, w_in - z_raw.lateral_margin_in), 1),
                clearance_type=z_raw.clearance_type,
                functional_clearance_in=z_raw.functional_clearance_in,
                calibration_layer=layer,
                reference_anchor_id=primary.anchor_id if primary else None,
                uncertainty_in=unc,
            )
        )

    cal = ScaleCalibrationResult(
        scope=parsed.resolved_scope,
        calibration_layer=1 if (primary and primary.tier != "architectural_variable") else 2,
        primary_anchor=primary,
        all_anchors=anchors,
        zones=zones,
        px_per_inch=consensus_rate,
        cross_anchor_skew_pct=skew_pct,
        foreshortening_flagged=foreshortened,
        exif_focal_mm=exif_focal_mm,
        exif_fx_px=f_px,
        uncertainty_in=max((z.uncertainty_in for z in zones), default=2.0),
        badge_label=(
            f"{primary.callout_text} · Video Walkthrough"
            if primary
            else f"Video Walkthrough + EXIF {exif_focal_mm:g}mm"
        ),
        thinking_level=thinking_level,
        image_width_px=frame_width_px,
        image_height_px=frame_height_px,
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )
    return parsed.spoken_transcript or fallback_prompt, parsed.extracted_budget_usd, cal

