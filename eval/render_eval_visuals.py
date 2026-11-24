"""Generate Blueprint CAD Measure overlays + Kinect Metric Depth heatmaps for all 14 eval rooms."""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
EVAL_DATA = ROOT / "eval" / "data"
RESULTS_PATH = ROOT / "eval" / "results.json"
MANIFEST_PATH = ROOT / "eval" / "manifest.json"


def _depth_to_heatmap(dep: np.ndarray) -> Image.Image:
    valid = dep[np.isfinite(dep) & (dep > 0.2) & (dep < 12.0)]
    lo = float(np.percentile(valid, 2)) if valid.size else 0.8
    hi = float(np.percentile(valid, 98)) if valid.size else 6.0
    norm = np.clip((dep - lo) / max(hi - lo, 0.1), 0.0, 1.0)
    # Clean architectural cyan-indigo-amber thermal ramp (near=warm amber, mid=cyan, far=deep navy)
    r = np.clip(1.5 - np.abs(4.0 * (1.0 - norm) - 3.0), 0.0, 1.0) * 255.0
    g = np.clip(1.5 - np.abs(4.0 * (1.0 - norm) - 2.0), 0.0, 1.0) * 255.0
    b = np.clip(1.5 - np.abs(4.0 * (1.0 - norm) - 1.0), 0.0, 1.0) * 255.0
    rgb = np.stack([r, g, b], axis=-1).astype(np.uint8)
    return Image.fromarray(rgb, mode="RGB")


def main() -> None:
    res = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    manifest = {r["room_id"]: r for r in json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("rooms", [])}

    for room in res.get("rooms", []):
        rid = room["room_id"]
        rgb_p = EVAL_DATA / f"{rid}_rgb.jpg"
        dep_p = EVAL_DATA / f"{rid}_depth.npy"
        if not rgb_p.exists() or not dep_p.exists():
            continue

        img = Image.open(rgb_p).convert("RGB")
        w, h = img.size
        bbox = (manifest.get(rid) or {}).get("reference_zone_bbox") or [320, 180, 860, 760]
        y1, x1 = int(bbox[0] / 1000.0 * h), int(bbox[1] / 1000.0 * w)
        y2, x2 = int(bbox[2] / 1000.0 * h), int(bbox[3] / 1000.0 * w)

        # 1. Blueprint Measure Overlay
        bp = img.copy()
        draw = ImageDraw.Draw(bp, "RGBA")
        draw.rectangle([x1, y1, x2, y2], fill=(56, 189, 248, 38), outline=(56, 189, 248, 255), width=3)
        # Top measure dimension bar
        cy = max(24, y1 - 16)
        draw.line([(x1, cy), (x2, cy)], fill=(56, 189, 248, 255), width=3)
        draw.line([(x1, cy - 8), (x1, cy + 8)], fill=(56, 189, 248, 255), width=3)
        draw.line([(x2, cy - 8), (x2, cy + 8)], fill=(56, 189, 248, 255), width=3)
        lbl = f"ClearBuy {room['clearbuy_est_width_in']:.1f}\" W  |  Kinect GT {room['kinect_gt_width_in']:.1f}\"  (Err ±{room['abs_scale_error_in']:.1f}\")"
        draw.rectangle([10, 10, min(w - 10, 440), 34], fill=(12, 13, 16, 225), outline=(56, 189, 248, 220), width=1)
        draw.text((18, 16), lbl, fill=(56, 189, 248, 255))
        cal_txt = str(room.get("calibration_summary") or "")[:68]
        draw.rectangle([10, h - 34, w - 10, h - 10], fill=(12, 13, 16, 225), outline=(16, 185, 129, 220), width=1)
        draw.text((18, h - 28), cal_txt, fill=(16, 185, 129, 255))
        bp.save(EVAL_DATA / f"{rid}_blueprint.jpg", format="JPEG", quality=90)

        # 2. Kinect Metric Depth Heatmap with same zone box
        dep = np.load(dep_p)
        hm = _depth_to_heatmap(dep).resize((w, h))
        d2 = ImageDraw.Draw(hm, "RGBA")
        d2.rectangle([x1, y1, x2, y2], outline=(255, 255, 255, 235), width=3)
        med_z = (manifest.get(rid) or {}).get("kinect_median_depth_m") or float(np.nanmedian(dep))
        d2.rectangle([10, 10, min(w - 10, 320), 34], fill=(12, 13, 16, 220))
        d2.text((18, 16), f"Kinect Metric Depth · Z_med = {med_z:.2f} m", fill=(244, 245, 247, 255))
        hm.save(EVAL_DATA / f"{rid}_depth.jpg", format="JPEG", quality=90)

    print("Generated blueprint + Kinect depth visuals for all 14 rooms.")


if __name__ == "__main__":
    main()
