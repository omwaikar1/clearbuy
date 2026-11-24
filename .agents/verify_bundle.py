#!/usr/bin/env python3
"""Universal deterministic 2D spatial topology, clearance & strict USD budget verifier.

Zero third-party dependencies (pure Python 3 stdlib) so it executes in <15 ms both:
1. Inside Google's Managed Agents remote Linux sandbox via `.agents/hooks.json`
   (`pre_tool_execution` / `PreToolUse` stdin -> stdout JSON gate).
2. Directly imported in FastAPI (`verify_bundle_dict`) for <1 ms `/swap` and `/zone` checks.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_CHAIR_KEYWORDS = ("chair", "stool", "seat", "bench")
_COFFEE_TABLE_KEYWORDS = ("coffee table", "ottoman", "pouf")
_SURFACE_KEYWORDS = (
    "table lamp",
    "desk lamp",
    "task lamp",
    "monitor",
    "desk mat",
    "organizer",
    "espresso",
    "speaker",
    "vase",
    "planter",
)
_UNDERLAY_KEYWORDS = ("rug", "runner", "carpet", "floor mat")
_WALL_MOUNT_KEYWORDS = ("wall art", "mirror", "poster", "print", "painting", "floating shelf", "sconce")


def infer_placement_mode(item: Dict[str, Any]) -> str:
    """Infer universal placement_mode if omitted or generic."""
    explicit = (item.get("placement_mode") or "").strip().lower()
    if explicit in ("floor_anchor", "underlay", "paired_tuck", "surface_top", "wall_mount"):
        # Double check obvious category mismatches (e.g. a rug mistakenly labeled floor_anchor)
        text = f"{item.get('category', '')} {item.get('title', '')}".lower()
        if explicit == "floor_anchor":
            if any(k in text for k in _UNDERLAY_KEYWORDS):
                return "underlay"
            if "desk mat" in text or any(k in text for k in ("table lamp", "desk lamp", "task lamp")):
                return "surface_top"
            if any(k in text for k in _WALL_MOUNT_KEYWORDS):
                return "wall_mount"
            if any(k in text for k in ("office chair", "ergonomic chair", "desk chair", "task chair", "dining chair")):
                return "paired_tuck"
        return explicit

    text = f"{item.get('category', '')} {item.get('title', '')}".lower()
    if any(k in text for k in _UNDERLAY_KEYWORDS):
        return "underlay"
    if any(k in text for k in _WALL_MOUNT_KEYWORDS):
        return "wall_mount"
    if any(k in text for k in _SURFACE_KEYWORDS):
        return "surface_top"
    if any(k in text for k in ("chair", "stool", "ottoman")) and "armchair" not in text and "lounge chair" not in text:
        return "paired_tuck"
    return "floor_anchor"


def compute_constraints_hash(constraints: Dict[str, Any]) -> str:
    """Deterministic SHA-256 over canonical constraints (excluding constraint_hash itself)."""
    filtered = {k: v for k, v in constraints.items() if k != "constraint_hash"}
    canonical = json.dumps(filtered, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_float(val: Any) -> Optional[float]:
    if val is None or isinstance(val, bool):
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def verify_bundle_dict(
    proposal: Dict[str, Any],
    constraints: Dict[str, Any],
    attempt: int = 1,
    expected_constraint_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """Deterministically verify a proposed cart bundle against calibrated room constraints.

    Returns a dict compatible with both Managed Agents hook stdout (`decision`, `reason`)
    and `HookTraceEvent` (`attempt`, `decision`, `reason`, `total_usd`, `budget_usd`,
    `violations`, `zone_summaries`, `timestamp_ms`).
    """
    violations: List[Dict[str, Any]] = []
    timestamp_ms = int(time.time() * 1000)

    # 1. Constraint integrity verification
    recorded_hash = expected_constraint_hash or constraints.get("constraint_hash")
    if recorded_hash:
        actual_hash = compute_constraints_hash(constraints)
        if actual_hash != recorded_hash:
            msg = "CONSTRAINT_TAMPERING: room_constraints.json integrity hash mismatch."
            return {
                "attempt": attempt,
                "decision": "deny",
                "reason": msg,
                "total_usd": 0.0,
                "budget_usd": float(constraints.get("budget_usd", 0.0) or 0.0),
                "violations": [
                    {
                        "code": "CONSTRAINT_TAMPERING",
                        "message": msg,
                    }
                ],
                "zone_summaries": {},
                "timestamp_ms": timestamp_ms,
            }

    budget_usd = _safe_float(constraints.get("budget_usd"))
    if budget_usd is None:
        budget_usd = _safe_float(proposal.get("budget_usd")) or 0.0

    items = proposal.get("items")
    if not isinstance(items, list) or len(items) == 0:
        msg = "EMPTY_BUNDLE: cart_proposal.json must contain at least 1 item in 'items'."
        return {
            "attempt": attempt,
            "decision": "deny",
            "reason": msg,
            "total_usd": 0.0,
            "budget_usd": round(budget_usd, 2),
            "violations": [{"code": "EMPTY_BUNDLE", "message": msg}],
            "zone_summaries": {},
            "timestamp_ms": timestamp_ms,
        }

    zones_list = constraints.get("zones") or []
    zones_by_id: Dict[str, Dict[str, Any]] = {
        str(z["zone_id"]): z for z in zones_list if isinstance(z, dict) and "zone_id" in z
    }
    protected_list = constraints.get("protected_anchors") or []
    require_shopify_gid = bool(constraints.get("require_shopify_gid", True))
    allow_unverified_primary = bool(constraints.get("allow_unverified_primary", False))

    # 2. Item-level SKU authenticity, cents-to-USD normalization & total budget check
    total_cents = 0
    total_usd = 0.0
    items_by_zone: Dict[str, List[Dict[str, Any]]] = {}

    for idx, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            continue
        item_id = str(raw_item.get("item_id") or f"item_{idx + 1}")
        sku_id = str(raw_item.get("sku_id") or "").strip()
        title = str(raw_item.get("title") or item_id).strip()
        zone_id = str(raw_item.get("zone_id") or "").strip()

        if require_shopify_gid and not (
            sku_id.startswith("gid://shopify/") or sku_id.startswith("shopify:")
        ):
            violations.append(
                {
                    "code": "INVALID_SKU_GID",
                    "zone_id": zone_id or None,
                    "item_id": item_id,
                    "sku_id": sku_id,
                    "message": (
                        f"Item '{title}' ({item_id}) has invalid Shopify GID '{sku_id}'. "
                        f"Every proposed SKU must come from live Shopify catalog with 'gid://shopify/...'."
                    ),
                }
            )

        raw_cents = raw_item.get("price_cents")
        raw_usd = _safe_float(raw_item.get("price_usd"))

        if raw_cents is not None:
            try:
                cents_int = int(round(float(raw_cents)))
            except (TypeError, ValueError):
                cents_int = -1
            if cents_int <= 0:
                violations.append(
                    {
                        "code": "PRICE_MISMATCH",
                        "zone_id": zone_id or None,
                        "item_id": item_id,
                        "sku_id": sku_id,
                        "message": f"Item '{title}' has non-positive price_cents ({raw_cents}).",
                    }
                )
                cents_int = 0
            expected_usd = round(cents_int / 100.0, 2)
            if raw_usd is not None and abs(raw_usd - expected_usd) > 0.02:
                violations.append(
                    {
                        "code": "PRICE_MISMATCH",
                        "zone_id": zone_id or None,
                        "item_id": item_id,
                        "sku_id": sku_id,
                        "measured_value": raw_usd,
                        "limit_value": expected_usd,
                        "message": (
                            f"Item '{title}' price_usd (${raw_usd:.2f}) does not match "
                            f"price_cents/100 (${expected_usd:.2f} from {cents_int} cents)."
                        ),
                    }
                )
            item_usd = expected_usd
            total_cents += cents_int
        elif raw_usd is not None and raw_usd > 0:
            item_usd = round(raw_usd, 2)
            total_cents += int(round(item_usd * 100))
        else:
            violations.append(
                {
                    "code": "PRICE_MISMATCH",
                    "zone_id": zone_id or None,
                    "item_id": item_id,
                    "sku_id": sku_id,
                    "message": f"Item '{title}' is missing valid positive price_cents / price_usd.",
                }
            )
            item_usd = 0.0

        total_usd = round(total_usd + item_usd, 2)

        if zone_id not in zones_by_id:
            violations.append(
                {
                    "code": "UNKNOWN_ZONE",
                    "zone_id": zone_id or None,
                    "item_id": item_id,
                    "sku_id": sku_id,
                    "message": (
                        f"Item '{title}' references unknown zone_id '{zone_id}'. "
                        f"Valid zones: {sorted(zones_by_id.keys())}."
                    ),
                }
            )
        else:
            enriched = dict(raw_item)
            enriched["_resolved_item_id"] = item_id
            enriched["_resolved_usd"] = item_usd
            enriched["_resolved_mode"] = infer_placement_mode(raw_item)
            items_by_zone.setdefault(zone_id, []).append(enriched)

    total_usd = round(total_cents / 100.0, 2)
    if budget_usd > 0 and total_usd > round(budget_usd, 2) + 1e-6:
        over_budget = round(total_usd - budget_usd, 2)
        breakdown = ", ".join(
            f"{it.get('title', it.get('item_id', 'item'))} (${(int(it.get('price_cents', round(float(it.get('price_usd', 0))*100)))/100.0):.2f})"
            for it in items
            if isinstance(it, dict)
        )
        violations.append(
            {
                "code": "BUDGET_EXCEEDED",
                "measured_value": total_usd,
                "limit_value": round(budget_usd, 2),
                "overflow_amount": over_budget,
                "message": (
                    f"Total bundle cost ${total_usd:.2f} exceeds strict budget ${budget_usd:.2f} "
                    f"by +${over_budget:.2f} ({breakdown}). Swap or downgrade item(s) to save at least ${over_budget:.2f}."
                ),
            }
        )

    # 3. Universal 2D Spatial Topology & Context-Parameterized Clearance Checks per Zone
    zone_summaries: Dict[str, str] = {}

    for zone_id, zone_items in items_by_zone.items():
        zone = zones_by_id[zone_id]
        zone_label = str(zone.get("label") or zone_id)
        zone_w = _safe_float(zone.get("width_in")) or 0.0
        zone_d = _safe_float(zone.get("depth_in")) or 0.0
        zone_h_limit = _safe_float(zone.get("height_limit_in"))
        enclosure_type = str(zone.get("enclosure_type") or "enclosed_alcove")

        lateral_margin = _safe_float(zone.get("lateral_margin_in"))
        if lateral_margin is None:
            if enclosure_type in ("enclosed_alcove", "corner_nook"):
                lateral_margin = 2.0
            elif enclosure_type in ("existing_surface", "floor_island", "wall_vertical"):
                lateral_margin = 0.0
            else:
                lateral_margin = 1.0

        usable_w = _safe_float(zone.get("usable_width_in"))
        if usable_w is None:
            usable_w = max(0.0, round(zone_w - lateral_margin, 2))
        else:
            # Always reconcile usable_w with zone_w - lateral_margin if zone_w was overridden
            usable_w = min(usable_w, max(0.0, round(zone_w - lateral_margin, 2)))

        clearance_type = str(zone.get("clearance_type") or "none")
        func_clearance = _safe_float(zone.get("functional_clearance_in"))
        if func_clearance is None:
            func_clearance = 24.0 if clearance_type in ("chair_pullout", "walkway", "door_swing") else (
                16.0 if clearance_type == "sofa_legroom" else 0.0
            )

        # Protected anchors linked to this zone (or global in single-zone upgrade mode)
        zone_protected = [
            p for p in protected_list
            if isinstance(p, dict) and (p.get("zone_id") in (None, "", zone_id) or len(zones_by_id) == 1)
        ]

        floor_anchors: List[Dict[str, Any]] = []
        underlays: List[Dict[str, Any]] = []
        paired_tucks: List[Dict[str, Any]] = []
        surface_tops: List[Dict[str, Any]] = []
        wall_mounts: List[Dict[str, Any]] = []

        for it in zone_items:
            mode = it["_resolved_mode"]
            if mode == "floor_anchor":
                floor_anchors.append(it)
            elif mode == "underlay":
                underlays.append(it)
            elif mode == "paired_tuck":
                paired_tucks.append(it)
            elif mode == "surface_top":
                surface_tops.append(it)
            elif mode == "wall_mount":
                wall_mounts.append(it)

            # Height check if zone has vertical ceiling/window sill constraint
            it_h = _safe_float(it.get("height_in"))
            if zone_h_limit is not None and it_h is not None and it_h > zone_h_limit + 1e-6:
                over_h = round(it_h - zone_h_limit, 2)
                violations.append(
                    {
                        "code": "HEIGHT_LIMIT_EXCEEDED",
                        "zone_id": zone_id,
                        "item_id": it["_resolved_item_id"],
                        "sku_id": it.get("sku_id"),
                        "measured_value": it_h,
                        "limit_value": zone_h_limit,
                        "overflow_amount": over_h,
                        "message": (
                            f"{it_h:.1f} in height of '{it.get('title')}' exceeds {zone_h_limit:.1f} in "
                            f"vertical limit in Zone {zone_id} (+{over_h:.1f} in overflow)."
                        ),
                    }
                )

        # 3A. Protected Anchor Collision Check ('upgrade' mode)
        if zone_protected:
            protected_cats = {
                str(p.get("category") or p.get("label") or "").lower() for p in zone_protected
            }
            for it in floor_anchors:
                it_cat = f"{it.get('category', '')} {it.get('title', '')}".lower()
                for p in zone_protected:
                    p_label = str(p.get("label") or p.get("category") or "").lower()
                    # Block replacing a kept desk/sofa/bed with another desk/sofa/bed in existing_surface or same slot
                    for core_noun in ("desk", "sofa", "couch", "bed", "dining table", "counter"):
                        if core_noun in p_label and core_noun in it_cat and f"{core_noun} mat" not in it_cat and f"{core_noun} lamp" not in it_cat and f"{core_noun} chair" not in it_cat:
                            violations.append(
                                {
                                    "code": "PROTECTED_ANCHOR_COLLISION",
                                    "zone_id": zone_id,
                                    "item_id": it["_resolved_item_id"],
                                    "sku_id": it.get("sku_id"),
                                    "message": (
                                        f"Item '{it.get('title')}' collides with protected kept furniture "
                                        f"'{p.get('label')}' in Zone {zone_id}. Preserve kept anchors and only add compatible upgrades."
                                    ),
                                }
                            )
                            break

        # 3B. Floor Anchor Lateral Width Sum + Lateral Margin Check
        anchor_width_sum = 0.0
        anchor_desc_parts: List[str] = []
        for it in floor_anchors:
            w = _safe_float(it.get("width_in"))
            unverified = bool(it.get("dimensions_unverified", False)) or (w is None)
            if unverified:
                if not allow_unverified_primary:
                    violations.append(
                        {
                            "code": "UNVERIFIED_PRIMARY_DIMENSIONS",
                            "zone_id": zone_id,
                            "item_id": it["_resolved_item_id"],
                            "sku_id": it.get("sku_id"),
                            "message": (
                                f"Primary floor anchor '{it.get('title')}' in Zone {zone_id} is missing verified "
                                f"width_in. Select a candidate SKU with verified physical dimensions."
                            ),
                        }
                    )
            else:
                assert w is not None
                anchor_width_sum = round(anchor_width_sum + w, 2)
                anchor_desc_parts.append(f"{w:.1f} in '{it.get('title')}'")

        if anchor_width_sum > usable_w + 1e-6 and zone_w > 0:
            overflow_w = round(anchor_width_sum - usable_w, 2)
            joined_desc = " + ".join(anchor_desc_parts) if len(anchor_desc_parts) > 1 else (
                anchor_desc_parts[0] if anchor_desc_parts else f"{anchor_width_sum:.1f} in items"
            )
            violations.append(
                {
                    "code": "ZONE_WIDTH_OVERFLOW",
                    "zone_id": zone_id,
                    "item_id": floor_anchors[0]["_resolved_item_id"] if len(floor_anchors) == 1 else None,
                    "sku_id": floor_anchors[0].get("sku_id") if len(floor_anchors) == 1 else None,
                    "measured_value": anchor_width_sum,
                    "limit_value": usable_w,
                    "overflow_amount": overflow_w,
                    "message": (
                        f"{joined_desc} ({anchor_width_sum:.1f} in total) exceeds {usable_w:.1f} in usable width "
                        f"in Zone {zone_id} ({zone_w:.1f} in {zone_label} minus {lateral_margin:.1f} in margin; "
                        f"+{overflow_w:.1f} in overflow). Choose SKU(s) <= {usable_w:.1f} in wide."
                    ),
                }
            )

        # 3C. Underlay (Area Rugs, Runners) Envelope Check — independent of furniture sitting on top!
        for it in underlays:
            uw = _safe_float(it.get("width_in"))
            ud = _safe_float(it.get("depth_in"))
            if uw is not None and zone_w > 0 and uw > zone_w + 1e-6:
                over_uw = round(uw - zone_w, 2)
                violations.append(
                    {
                        "code": "UNDERLAY_OVERFLOW",
                        "zone_id": zone_id,
                        "item_id": it["_resolved_item_id"],
                        "sku_id": it.get("sku_id"),
                        "measured_value": uw,
                        "limit_value": zone_w,
                        "overflow_amount": over_uw,
                        "message": (
                            f"Underlay/rug '{it.get('title')}' width ({uw:.1f} in) exceeds Zone {zone_id} "
                            f"floor width ({zone_w:.1f} in; +{over_uw:.1f} in overflow)."
                        ),
                    }
                )
            if ud is not None and zone_d > 0 and ud > zone_d + 1e-6:
                over_ud = round(ud - zone_d, 2)
                violations.append(
                    {
                        "code": "UNDERLAY_OVERFLOW",
                        "zone_id": zone_id,
                        "item_id": it["_resolved_item_id"],
                        "sku_id": it.get("sku_id"),
                        "measured_value": ud,
                        "limit_value": zone_d,
                        "overflow_amount": over_ud,
                        "message": (
                            f"Underlay/rug '{it.get('title')}' depth ({ud:.1f} in) exceeds Zone {zone_id} "
                            f"floor depth ({zone_d:.1f} in; +{over_ud:.1f} in overflow)."
                        ),
                    }
                )

        # 3D. Surface-Top Items (Desk Lamps, Monitors, Desk Mats, Organizers)
        if surface_tops:
            # Determine available parent surface width & depth from floor_anchor or protected_anchor
            parent_w_candidates: List[float] = []
            parent_d_candidates: List[float] = []
            for fa in floor_anchors:
                fw = _safe_float(fa.get("width_in"))
                fd = _safe_float(fa.get("depth_in"))
                if fw:
                    parent_w_candidates.append(fw)
                if fd:
                    parent_d_candidates.append(fd)
            for pa in zone_protected:
                if pa.get("supports_surface_items", True):
                    pw = _safe_float(pa.get("estimated_width_in"))
                    pd = _safe_float(pa.get("estimated_depth_in"))
                    if pw:
                        parent_w_candidates.append(pw)
                    if pd:
                        parent_d_candidates.append(pd)
            surface_limit_w = max(parent_w_candidates) if parent_w_candidates else zone_w
            surface_limit_d = max(parent_d_candidates) if parent_d_candidates else zone_d

            for it in surface_tops:
                sw = _safe_float(it.get("width_in"))
                sd = _safe_float(it.get("depth_in"))
                if sw is not None and surface_limit_w > 0 and sw > surface_limit_w + 1e-6:
                    over_sw = round(sw - surface_limit_w, 2)
                    violations.append(
                        {
                            "code": "SURFACE_OVERFLOW",
                            "zone_id": zone_id,
                            "item_id": it["_resolved_item_id"],
                            "sku_id": it.get("sku_id"),
                            "measured_value": sw,
                            "limit_value": surface_limit_w,
                            "overflow_amount": over_sw,
                            "message": (
                                f"Surface item '{it.get('title')}' ({sw:.1f} in W) exceeds supporting surface width "
                                f"({surface_limit_w:.1f} in) in Zone {zone_id} (+{over_sw:.1f} in overflow)."
                            ),
                        }
                    )
                if sd is not None and surface_limit_d > 0 and sd > surface_limit_d + 1e-6:
                    over_sd = round(sd - surface_limit_d, 2)
                    violations.append(
                        {
                            "code": "SURFACE_OVERFLOW",
                            "zone_id": zone_id,
                            "item_id": it["_resolved_item_id"],
                            "sku_id": it.get("sku_id"),
                            "measured_value": sd,
                            "limit_value": surface_limit_d,
                            "overflow_amount": over_sd,
                            "message": (
                                f"Surface item '{it.get('title')}' ({sd:.1f} in D) exceeds supporting surface depth "
                                f"({surface_limit_d:.1f} in) in Zone {zone_id} (+{over_sd:.1f} in overflow)."
                            ),
                        }
                    )

        # 3E. Wall-Mount Items (Framed Art, Mirrors, Floating Shelves)
        for it in wall_mounts:
            ww = _safe_float(it.get("width_in"))
            if ww is not None and zone_w > 0 and ww > zone_w + 1e-6:
                over_ww = round(ww - zone_w, 2)
                violations.append(
                    {
                        "code": "WALL_MOUNT_OVERFLOW",
                        "zone_id": zone_id,
                        "item_id": it["_resolved_item_id"],
                        "sku_id": it.get("sku_id"),
                        "measured_value": ww,
                        "limit_value": zone_w,
                        "overflow_amount": over_ww,
                        "message": (
                            f"Wall-mounted item '{it.get('title')}' ({ww:.1f} in W) exceeds Zone {zone_id} "
                            f"wall width ({zone_w:.1f} in; +{over_ww:.1f} in overflow)."
                        ),
                    }
                )

        # 3F. Depth Envelope & Context-Parameterized Functional Clearance Check
        if zone_d > 0:
            anchor_depths = [
                d for d in (_safe_float(fa.get("depth_in")) for fa in floor_anchors) if d is not None
            ]
            for pa in zone_protected:
                pd = _safe_float(pa.get("estimated_depth_in"))
                if pd is not None:
                    anchor_depths.append(pd)
            max_anchor_d = max(anchor_depths) if anchor_depths else 0.0

            # Inspect paired_tuck items (chairs vs coffee tables/ottomans)
            has_pullout_seating = any(
                any(k in f"{pt.get('category', '')} {pt.get('title', '')}".lower() for k in _CHAIR_KEYWORDS)
                for pt in paired_tucks
            )
            coffee_table_depths = [
                _safe_float(pt.get("depth_in")) or 0.0
                for pt in paired_tucks
                if any(k in f"{pt.get('category', '')} {pt.get('title', '')}".lower() for k in _COFFEE_TABLE_KEYWORDS)
            ]
            max_coffee_d = max(coffee_table_depths) if coffee_table_depths else 0.0

            # Paired seating must also fit width-wise inside the zone!
            for pt in paired_tucks:
                pt_w = _safe_float(pt.get("width_in"))
                if pt_w is not None and zone_w > 0 and pt_w > zone_w + 1e-6:
                    over_pw = round(pt_w - zone_w, 2)
                    violations.append(
                        {
                            "code": "ZONE_WIDTH_OVERFLOW",
                            "zone_id": zone_id,
                            "item_id": pt["_resolved_item_id"],
                            "sku_id": pt.get("sku_id"),
                            "measured_value": pt_w,
                            "limit_value": zone_w,
                            "overflow_amount": over_pw,
                            "message": (
                                f"Paired item '{pt.get('title')}' ({pt_w:.1f} in W) exceeds Zone {zone_id} "
                                f"width ({zone_w:.1f} in; +{over_pw:.1f} in overflow)."
                            ),
                        }
                    )

            effective_clearance = func_clearance
            if has_pullout_seating and effective_clearance < 24.0:
                effective_clearance = 24.0
            elif max_coffee_d > 0 and effective_clearance < 16.0:
                effective_clearance = 16.0

            # Only enforce anchor+clearance depth when an anchor or paired item occupies depth
            if max_anchor_d > 0 or has_pullout_seating or max_coffee_d > 0:
                if max_anchor_d == 0.0 and paired_tucks:
                    # Standalone chair/ottoman in a zone without a desk/sofa
                    pt_depths = [
                        d for d in (_safe_float(pt.get("depth_in")) for pt in paired_tucks) if d is not None
                    ]
                    occupied_d = max(pt_depths) if pt_depths else 0.0
                    required_d = round(occupied_d + func_clearance, 2)
                else:
                    required_d = round(max_anchor_d + max_coffee_d + effective_clearance, 2)

                if required_d > zone_d + 1e-6:
                    over_d = round(required_d - zone_d, 2)
                    code = (
                        "WALKWAY_CLEARANCE_VIOLATION"
                        if clearance_type in ("walkway", "door_swing")
                        else "DEPTH_CLEARANCE_VIOLATION"
                    )
                    clearance_label = (
                        "24.0 in ergonomic chair pull-out"
                        if has_pullout_seating
                        else f"{effective_clearance:.1f} in {clearance_type.replace('_', ' ')} clearance"
                    )
                    violations.append(
                        {
                            "code": code,
                            "zone_id": zone_id,
                            "measured_value": required_d,
                            "limit_value": zone_d,
                            "overflow_amount": over_d,
                            "message": (
                                f"Zone {zone_id} depth envelope ({max_anchor_d:.1f} in anchor depth"
                                + (f" + {max_coffee_d:.1f} in paired table" if max_coffee_d > 0 else "")
                                + f" + {clearance_label} = {required_d:.1f} in) exceeds available "
                                f"{zone_d:.1f} in depth (+{over_d:.1f} in overflow). Choose a shallower SKU."
                            ),
                        }
                    )

        zone_summaries[zone_id] = (
            f"Anchor W {anchor_width_sum:.1f}\" / {usable_w:.1f}\" usable "
            f"(Zone {zone_w:.1f}\"W x {zone_d:.1f}\"D, {len(zone_items)} item(s))"
        )

    if violations:
        combined_reason = " | ".join(v["message"] for v in violations)
        return {
            "attempt": attempt,
            "decision": "deny",
            "reason": combined_reason,
            "total_usd": total_usd,
            "budget_usd": round(budget_usd, 2),
            "violations": violations,
            "zone_summaries": zone_summaries,
            "timestamp_ms": timestamp_ms,
        }

    summary_str = "; ".join(f"{zid}: {txt}" for zid, txt in zone_summaries.items())
    return {
        "attempt": attempt,
        "decision": "allow",
        "reason": (
            f"VERIFIED ALLOW: {len(items)} item(s) fit all spatial zones ({summary_str}) "
            f"and total ${total_usd:.2f} <= ${budget_usd:.2f} budget."
        ),
        "total_usd": total_usd,
        "budget_usd": round(budget_usd, 2),
        "violations": [],
        "zone_summaries": zone_summaries,
        "timestamp_ms": timestamp_ms,
    }


def _find_workspace_file(filename: str, cwd: Optional[str] = None) -> Optional[Path]:
    """Locate room_constraints.json or hook_trace.jsonl in /workspace or local CWD."""
    candidates = [
        Path("/workspace") / filename,
    ]
    if cwd:
        candidates.append(Path(cwd) / filename)
    candidates.append(Path.cwd() / filename)
    for p in candidates:
        if p.exists():
            return p
    return None


def _append_hook_trace(event: Dict[str, Any], cwd: Optional[str] = None) -> int:
    """Append HookTraceEvent JSONL to /workspace/hook_trace.jsonl (or CWD) and return attempt #."""
    target_dir = Path("/workspace") if Path("/workspace").exists() and os.access("/workspace", os.W_OK) else (
        Path(cwd) if cwd and Path(cwd).exists() else Path.cwd()
    )
    trace_file = target_dir / "hook_trace.jsonl"
    attempt_num = 1
    if trace_file.exists():
        try:
            with trace_file.open("r", encoding="utf-8") as fh:
                attempt_num = sum(1 for line in fh if line.strip()) + 1
        except OSError:
            attempt_num = 1
    event["attempt"] = attempt_num
    try:
        with trace_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
    except OSError:
        pass
    return attempt_num


def _extract_tool_info(hook_input: Dict[str, Any]) -> Tuple[str, Dict[str, Any], Optional[str]]:
    """Support both Managed Agents snake_case (`tool_call`) and Antigravity camelCase (`toolCall`)."""
    tc = hook_input.get("tool_call") or hook_input.get("toolCall") or {}
    name = str(tc.get("name") or "").strip()
    args = tc.get("args") or tc.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {"raw": args}
    cwd = hook_input.get("cwd")
    return name, args if isinstance(args, dict) else {}, cwd


def _extract_target_path(args: Dict[str, Any]) -> str:
    for key in ("path", "file_path", "target_file", "TargetFile", "Path", "filename", "target"):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _extract_file_content(args: Dict[str, Any]) -> Optional[str]:
    for key in ("content", "Content", "file_text", "CodeContent", "text", "new_content", "Replacement"):
        val = args.get(key)
        if isinstance(val, str):
            return val
    return None


def verify_api_payload(payload: Dict[str, Any], attempt: int = 1) -> Dict[str, Any]:
    """Normalize the FastAPI adapter's `{budget_usd, zones, items}` (`ShopifySKU`) payload and run `verify_bundle_dict`."""
    budget_usd = _safe_float(payload.get("budget_usd")) or 0.0
    raw_zones = payload.get("zones") or []
    norm_zones: List[Dict[str, Any]] = []
    for idx, rz in enumerate(raw_zones):
        if not isinstance(rz, dict):
            continue
        zid = str(rz.get("zone_id") or f"zone_{idx + 1}")
        lat_margin = _safe_float(rz.get("lateral_margin_in"))
        if lat_margin is None:
            lat_margin = _safe_float(rz.get("wall_margin_in"))
        if lat_margin is None:
            lat_margin = 2.0
        func_clr = _safe_float(rz.get("functional_clearance_in"))
        if func_clr is None:
            func_clr = _safe_float(rz.get("clearance_required_in"))
        if func_clr is None:
            func_clr = 24.0
        w_in = _safe_float(rz.get("width_in")) or 43.5
        d_in = _safe_float(rz.get("depth_in")) or 60.0
        usable_w = _safe_float(rz.get("usable_width_in"))
        if usable_w is None:
            usable_w = round(max(0.0, w_in - lat_margin), 2)
        norm_zones.append(
            {
                "zone_id": zid,
                "label": rz.get("label") or zid,
                "enclosure_type": rz.get("enclosure_type") or "enclosed_alcove",
                "width_in": w_in,
                "depth_in": d_in,
                "lateral_margin_in": lat_margin,
                "usable_width_in": usable_w,
                "clearance_type": rz.get("clearance_type") or ("chair_pullout" if func_clr >= 24.0 else "none"),
                "functional_clearance_in": func_clr,
            }
        )

    default_zid = norm_zones[0]["zone_id"] if norm_zones else "zone_1"
    if not norm_zones:
        # When session.scale is absent (e.g., checkout-only unit fixtures), enforce budget/price only
        norm_zones = [
            {
                "zone_id": default_zid,
                "label": "Unconstrained Checkout Zone",
                "enclosure_type": "open_wall",
                "width_in": 9999.0,
                "depth_in": 9999.0,
                "lateral_margin_in": 0.0,
                "usable_width_in": 9999.0,
                "clearance_type": "none",
                "functional_clearance_in": 0.0,
            }
        ]
    known_zone_ids = {z["zone_id"] for z in norm_zones}
    norm_items: List[Dict[str, Any]] = []
    for idx, it in enumerate(payload.get("items") or []):
        if not isinstance(it, dict):
            continue
        dims = it.get("dimensions") if isinstance(it.get("dimensions"), dict) else {}
        w_in = _safe_float(it.get("width_in"))
        if w_in is None:
            w_in = _safe_float(dims.get("width_in"))
        d_in = _safe_float(it.get("depth_in"))
        if d_in is None:
            d_in = _safe_float(dims.get("depth_in"))
        h_in = _safe_float(it.get("height_in"))
        if h_in is None:
            h_in = _safe_float(dims.get("height_in"))
        unv = bool(
            it.get("dimensions_unverified")
            if "dimensions_unverified" in it
            else dims.get("dimensions_unverified", w_in is None)
        )
        gid = str(it.get("gid") or it.get("sku_id") or f"gid://shopify/Product/{idx + 1}")
        raw_item_zid = str(it.get("zone_id") or default_zid)
        resolved_zid = raw_item_zid if raw_item_zid in known_zone_ids else default_zid
        norm_items.append(
            {
                "item_id": str(it.get("item_id") or it.get("sku_id") or f"item_{idx + 1}"),
                "zone_id": resolved_zid,
                "sku_id": gid if gid.startswith("gid://shopify/") else f"gid://shopify/Product/{gid}",
                "title": str(it.get("title") or f"item_{idx + 1}"),
                "price_cents": it.get("price_cents", int(round(float(it.get("price_usd", 0.0) or 0.0) * 100))),
                "price_usd": it.get("price_usd"),
                "width_in": w_in,
                "depth_in": d_in,
                "height_in": h_in,
                "dimensions_unverified": unv,
                "placement_mode": it.get("placement_mode"),
                "category": str(it.get("category") or "furniture"),
            }
        )

    constraints_dict = {
        "budget_usd": budget_usd,
        "zones": norm_zones,
        "protected_anchors": payload.get("protected_anchors") or [],
        "require_shopify_gid": False,
        "allow_unverified_primary": True,
    }
    proposal_dict = {
        "budget_usd": budget_usd,
        "items": norm_items,
    }
    return verify_bundle_dict(proposal_dict, constraints_dict, attempt=attempt)


def handle_hook_stdin(raw_stdin: str) -> Dict[str, Any]:
    """Process either a Managed Agents `pre_tool_execution` payload OR the FastAPI adapter's `{budget_usd, zones, items}` JSON."""
    if not raw_stdin.strip():
        return {"decision": "allow"}
    try:
        payload = json.loads(raw_stdin)
    except json.JSONDecodeError:
        return {"decision": "allow"}

    # Direct FastAPI adapter invocation (`{"budget_usd": ..., "zones": [...], "items": [...]}`)
    if isinstance(payload, dict) and "items" in payload and "zones" in payload and "tool_call" not in payload and "toolCall" not in payload:
        res = verify_api_payload(payload)
        if res["decision"] == "deny":
            return {"decision": "deny", "reason": res["reason"]}
        return {"decision": "allow"}

    tool_name, args, cwd = _extract_tool_info(payload)
    target_path = _extract_target_path(args)
    target_lower = target_path.lower()

    # 1. Block any attempt to tamper with room_constraints.json or verify_bundle.py / hooks.json
    if any(
        protected_name in target_lower
        for protected_name in ("room_constraints.json", "verify_bundle.py", "hooks.json")
    ):
        deny_event = {
            "decision": "deny",
            "reason": (
                f"CONSTRAINT_TAMPERING: '{target_path}' is protected read-only physical ground truth "
                f"and cannot be modified."
            ),
            "violations": [{"code": "CONSTRAINT_TAMPERING", "message": f"Blocked write to {target_path}"}],
            "timestamp_ms": int(time.time() * 1000),
        }
        _append_hook_trace(deny_event, cwd=cwd)
        return {"decision": "deny", "reason": deny_event["reason"]}

    # 2. Block shell/code_execution bypasses writing cart_proposal.json or room_constraints.json directly
    if tool_name in ("code_execution", "run_command", "bash"):
        code_str = " ".join(
            str(args.get(k, "")) for k in ("code", "command", "CommandLine", "cmd", "script")
        )
        if "room_constraints.json" in code_str and re.search(
            r"(open\s*\([^)]*['\"][wa]|write_text|>\s*.*room_constraints|rm\s+|mv\s+|cp\s+)",
            code_str,
        ):
            reason = "CONSTRAINT_TAMPERING: Modifying room_constraints.json via code_execution is forbidden."
            _append_hook_trace(
                {
                    "decision": "deny",
                    "reason": reason,
                    "violations": [{"code": "CONSTRAINT_TAMPERING", "message": reason}],
                    "timestamp_ms": int(time.time() * 1000),
                },
                cwd=cwd,
            )
            return {"decision": "deny", "reason": reason}

        if "cart_proposal.json" in code_str and re.search(
            r"(open\s*\([^)]*['\"][wa]|write_text|json\.dump|>\s*.*cart_proposal|tee\s+.*cart_proposal|mv\s+|cp\s+)",
            code_str,
        ):
            reason = (
                "COMMIT_PROTOCOL_REQUIRED: Save /workspace/cart_proposal.json exclusively via the "
                "`write_to_file` tool (not code_execution) so the deterministic spatial & budget guardrail "
                "can verify your bundle."
            )
            return {"decision": "deny", "reason": reason}

        return {"decision": "allow"}

    # 3. Intercept writes/edits targeting cart_proposal.json
    if not target_lower.endswith("cart_proposal.json"):
        return {"decision": "allow"}

    content_str = _extract_file_content(args)
    if content_str is None:
        reason = "EMPTY_BUNDLE: Missing JSON content when writing cart_proposal.json."
        return {"decision": "deny", "reason": reason}

    # Handle replace_file_content if an existing cart_proposal.json is being patched
    if tool_name in ("replace_file_content", "edit_file"):
        existing_path = Path(target_path) if Path(target_path).is_absolute() else (
            (Path(cwd) / target_path) if cwd else Path(target_path)
        )
        target_sub = args.get("target") or args.get("old_str") or args.get("Target")
        replacement_sub = args.get("replacement") or args.get("new_str") or args.get("Replacement")
        if existing_path.exists() and isinstance(target_sub, str) and isinstance(replacement_sub, str):
            content_str = existing_path.read_text(encoding="utf-8").replace(target_sub, replacement_sub)

    try:
        proposal_dict = json.loads(content_str)
    except json.JSONDecodeError as exc:
        reason = f"INVALID_JSON: cart_proposal.json must be valid JSON ({exc})."
        _append_hook_trace(
            {
                "decision": "deny",
                "reason": reason,
                "violations": [{"code": "EMPTY_BUNDLE", "message": reason}],
                "timestamp_ms": int(time.time() * 1000),
            },
            cwd=cwd,
        )
        return {"decision": "deny", "reason": reason}

    constraints_path = _find_workspace_file("room_constraints.json", cwd=cwd)
    if constraints_path is None:
        # Fallback if constraints embedded or env variable set
        env_constraints = os.getenv("CLEARBUY_CONSTRAINTS_JSON")
        if env_constraints:
            constraints_dict = json.loads(env_constraints)
        else:
            constraints_dict = {
                "budget_usd": proposal_dict.get("budget_usd", 0.0),
                "zones": proposal_dict.get("zones", []),
            }
    else:
        constraints_dict = json.loads(constraints_path.read_text(encoding="utf-8"))

    result = verify_bundle_dict(proposal_dict, constraints_dict)
    _append_hook_trace(result, cwd=cwd)

    if result["decision"] == "deny":
        return {
            "decision": "deny",
            "reason": result["reason"],
        }
    return {"decision": "allow"}


def main() -> None:
    raw = sys.stdin.read()
    out = handle_hook_stdin(raw)
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
