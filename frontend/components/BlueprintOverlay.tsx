"use client";

import React, { useRef, useState } from "react";
import type { DetectedZone, ScaleReadyEvent } from "@/types/clearbuy";

interface BlueprintOverlayProps {
  scaleData: ScaleReadyEvent;
  isRendering: boolean;
  onOverrideZoneWidth: (zone: DetectedZone, newWidthIn: number) => void;
  onSelectZone?: (zone: DetectedZone) => void;
}

/**
 * Interactive SVG CAD Measure Overlay operating on Gemini 4 Neon's 0–1000 normalized grid.
 * Draws:
 *  1) Dashed cyan Reference Anchor Callout (e.g., US Outlet · 4.5" H → 14.2 px/in) + leader line
 *  2) Protected Anchor amber masks for kept furniture (Setup Upgrade mode)
 *  3) Numbered zone bounding boxes with end-capped measuring lines (|◄—— 43.5" W ——►|) + 24" clearance arc
 *  4) Hover-revealed dual drag handles (left + right, gently highlighted in Layer 2 fallback)
 *  5) Click-on-zone to drop @Zone scope chip into VoiceSpatialThread
 */
export function BlueprintOverlay({
  scaleData,
  isRendering,
  onOverrideZoneWidth,
  onSelectZone,
}: BlueprintOverlayProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [draggingZoneId, setDraggingZoneId] = useState<string | null>(null);
  const [dragPreviewWidth, setDragPreviewWidth] = useState<number | null>(null);
  const dragStartRef = useRef<{
    clientX: number;
    baseWidthIn: number;
    side: "left" | "right";
  } | null>(null);

  const primaryAnchor = scaleData.anchors[0];
  const primaryZone = scaleData.zones[0];
  const isLayer2 = scaleData.calibration_layer === "layer2_depth_exif";

  const handlePointerDown = (
    e: React.PointerEvent,
    zone: DetectedZone,
    side: "left" | "right"
  ) => {
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    setDraggingZoneId(zone.zone_id);
    setDragPreviewWidth(zone.width_in);
    dragStartRef.current = {
      clientX: e.clientX,
      baseWidthIn: zone.width_in,
      side,
    };
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!draggingZoneId || !dragStartRef.current) return;
    const rawDx = e.clientX - dragStartRef.current.clientX;
    const dxPx = dragStartRef.current.side === "left" ? -rawDx : rawDx;
    const nextWidth = Math.max(
      18,
      Math.min(180, Math.round((dragStartRef.current.baseWidthIn + dxPx / 6) * 2) / 2)
    );
    setDragPreviewWidth(nextWidth);
  };

  const handlePointerUp = (e: React.PointerEvent, zone: DetectedZone) => {
    if (!draggingZoneId) return;
    (e.target as Element).releasePointerCapture(e.pointerId);
    const finalWidth = dragPreviewWidth ?? zone.width_in;
    setDraggingZoneId(null);
    setDragPreviewWidth(null);
    dragStartRef.current = null;
    if (Math.abs(finalWidth - zone.width_in) >= 0.5) {
      onOverrideZoneWidth(zone, finalWidth);
    }
  };

  return (
    <div className="absolute inset-0 pointer-events-none select-none overflow-hidden">
      {/* Subtle 2.4s architectural scan-line while Nano Banana renders */}
      {isRendering && (
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="w-full h-16 bg-gradient-to-b from-transparent via-[#38BDF8]/20 to-transparent border-b border-[#38BDF8]/50 animate-clearbuy-scanline" />
        </div>
      )}

      <svg
        ref={svgRef}
        viewBox="0 0 1000 1000"
        preserveAspectRatio="none"
        className="w-full h-full"
      >
        <defs>
          <marker
            id="cad-arrow-left"
            viewBox="0 0 10 10"
            refX="2"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto"
          >
            <path d="M 10 1 L 0 5 L 10 9 z" fill="#38BDF8" />
          </marker>
          <marker
            id="cad-arrow-right"
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto"
          >
            <path d="M 0 1 L 10 5 L 0 9 z" fill="#38BDF8" />
          </marker>
        </defs>

        {/* Protected Anchor Masks (Kept Furniture in Setup Upgrade Mode) */}
        {(scaleData.protected_anchors ?? []).map((pa, idx) => {
          const [y1, x1, y2, x2] = pa.bbox;
          const w = x2 - x1;
          const h = y2 - y1;
          return (
            <g key={`pa-${idx}`}>
              <rect
                x={x1}
                y={y1}
                width={w}
                height={h}
                fill="rgba(245, 158, 11, 0.14)"
                stroke="#F59E0B"
                strokeWidth="2.5"
                strokeDasharray="8 5"
                rx="4"
              />
              <rect
                x={x1 + 6}
                y={y1 + 6}
                width="176"
                height="26"
                rx="5"
                fill="#0C0D10"
                fillOpacity="0.88"
                stroke="#F59E0B"
                strokeWidth="1.2"
              />
              <text
                x={x1 + 14}
                y={y1 + 23}
                fill="#F59E0B"
                fontSize="13"
                fontFamily="monospace"
                fontWeight="600"
              >
                Protected · {pa.label.slice(0, 14)}
              </text>
            </g>
          );
        })}

        {/* Reference Anchor Callout Boxes (Layer 1) */}
        {scaleData.anchors.map((anchor, idx) => {
          const [y1, x1, y2, x2] = anchor.bbox;
          const w = x2 - x1;
          const h = y2 - y1;
          return (
            <g key={anchor.id}>
              <rect
                x={x1}
                y={y1}
                width={w}
                height={h}
                fill="rgba(56, 189, 248, 0.14)"
                stroke="#38BDF8"
                strokeWidth="2.5"
                strokeDasharray="6 4"
                rx="3"
              />
              {idx === 0 && primaryZone && (
                <line
                  x1={x2}
                  y1={(y1 + y2) / 2}
                  x2={primaryZone.bbox[1]}
                  y2={(primaryZone.bbox[0] + primaryZone.bbox[2]) / 2}
                  stroke="#38BDF8"
                  strokeWidth="1.5"
                  strokeDasharray="4 4"
                  opacity="0.75"
                />
              )}
            </g>
          );
        })}

        {/* Detected Placement Zones + Dual Hover-Revealed Measure Handles */}
        {scaleData.zones.map((zone) => {
          const [y1, x1, y2, x2] = zone.bbox;
          const w = x2 - x1;
          const h = y2 - y1;
          const midX = (x1 + x2) / 2;
          const measureY = Math.max(40, y1 - 22);
          const displayWidth =
            draggingZoneId === zone.zone_id && dragPreviewWidth !== null
              ? dragPreviewWidth
              : zone.width_in;

          const handleVisibilityClass =
            isLayer2 || draggingZoneId === zone.zone_id
              ? "opacity-100"
              : "opacity-35 group-hover:opacity-100 transition-opacity";

          return (
            <g key={zone.zone_id} className="group">
              {/* Clickable Zone Box -> drops @Zone chip into VoiceSpatialThread */}
              <rect
                x={x1}
                y={y1}
                width={w}
                height={h}
                fill={
                  zone.protected_anchor
                    ? "rgba(245, 158, 11, 0.10)"
                    : "rgba(56, 189, 248, 0.08)"
                }
                stroke={zone.protected_anchor ? "#F59E0B" : "#38BDF8"}
                strokeWidth="2"
                rx="4"
                className="pointer-events-auto cursor-pointer"
                onClick={() => onSelectZone?.(zone)}
              >
                <title>Click to target {zone.label} in Voice Swap Thread</title>
              </rect>

              {/* Corner CAD brackets */}
              <path
                d={`M ${x1} ${y1 + 18} L ${x1} ${y1} L ${x1 + 18} ${y1}`}
                fill="none"
                stroke="#38BDF8"
                strokeWidth="3.5"
              />
              <path
                d={`M ${x2 - 18} ${y1} L ${x2} ${y1} L ${x2} ${y1 + 18}`}
                fill="none"
                stroke="#38BDF8"
                strokeWidth="3.5"
              />
              <path
                d={`M ${x1} ${y2 - 18} L ${x1} ${y2} L ${x1 + 18} ${y2}`}
                fill="none"
                stroke="#38BDF8"
                strokeWidth="3.5"
              />
              <path
                d={`M ${x2 - 18} ${y2} L ${x2} ${y2} L ${x2} ${y2 - 18}`}
                fill="none"
                stroke="#38BDF8"
                strokeWidth="3.5"
              />

              {/* End-Capped Width Measure (|◄—— 43.5" W ——►|) */}
              <line
                x1={x1}
                y1={measureY - 10}
                x2={x1}
                y2={measureY + 10}
                stroke="#38BDF8"
                strokeWidth="2.5"
              />
              <line
                x1={x2}
                y1={measureY - 10}
                x2={x2}
                y2={measureY + 10}
                stroke="#38BDF8"
                strokeWidth="2.5"
              />
              <line
                x1={x1 + 4}
                y1={measureY}
                x2={x2 - 4}
                y2={measureY}
                stroke="#38BDF8"
                strokeWidth="2"
                markerStart="url(#cad-arrow-left)"
                markerEnd="url(#cad-arrow-right)"
              />

              {/* 24" Chair Pull-Out / Walkway Clearance Arc */}
              {zone.clearance_in && (
                <path
                  d={`M ${x1 + w * 0.15} ${y2} Q ${midX} ${Math.min(
                    980,
                    y2 + 65
                  )} ${x2 - w * 0.15} ${y2}`}
                  fill="rgba(56, 189, 248, 0.06)"
                  stroke="#38BDF8"
                  strokeWidth="1.5"
                  strokeDasharray="5 5"
                />
              )}

              {/* Left Hover-Revealed Drag Handle */}
              <circle
                cx={x1}
                cy={measureY}
                r="11"
                fill={
                  draggingZoneId === zone.zone_id
                    ? "#38BDF8"
                    : isLayer2
                    ? "#F59E0B"
                    : "#0C0D10"
                }
                stroke={isLayer2 ? "#F59E0B" : "#38BDF8"}
                strokeWidth="2.5"
                className={`pointer-events-auto cursor-ew-resize ${handleVisibilityClass}`}
                onPointerDown={(e) => handlePointerDown(e, zone, "left")}
                onPointerMove={handlePointerMove}
                onPointerUp={(e) => handlePointerUp(e, zone)}
              >
                <title>Drag to override {zone.zone_id} width</title>
              </circle>

              {/* Right Hover-Revealed Drag Handle */}
              <circle
                cx={x2}
                cy={measureY}
                r="11"
                fill={
                  draggingZoneId === zone.zone_id
                    ? "#38BDF8"
                    : isLayer2
                    ? "#F59E0B"
                    : "#0C0D10"
                }
                stroke={isLayer2 ? "#F59E0B" : "#38BDF8"}
                strokeWidth="2.5"
                className={`pointer-events-auto cursor-ew-resize ${handleVisibilityClass}`}
                onPointerDown={(e) => handlePointerDown(e, zone, "right")}
                onPointerMove={handlePointerMove}
                onPointerUp={(e) => handlePointerUp(e, zone)}
              >
                <title>Drag to override {zone.zone_id} width</title>
              </circle>

              {/* Inline SVG width pill */}
              <rect
                x={midX - 68}
                y={measureY - 16}
                width="136"
                height="28"
                rx="6"
                fill="#0C0D10"
                fillOpacity="0.92"
                stroke="#38BDF8"
                strokeWidth="1.5"
              />
              <text
                x={midX}
                y={measureY + 3}
                textAnchor="middle"
                fill="#F4F5F7"
                fontSize="16"
                fontFamily="monospace"
                fontWeight="600"
              >
                {zone.zone_id} · {displayWidth.toFixed(1)}&quot; W
              </text>
            </g>
          );
        })}
      </svg>

      {/* Crisp HTML Anchor Callout Pill */}
      {primaryAnchor && scaleData.calibration_layer === "layer1_anchor" && (
        <div
          className="absolute px-2.5 py-1 rounded-md bg-[#0C0D10]/92 border border-[#38BDF8]/70 text-[11px] font-mono tabular-nums-strict text-[#38BDF8] shadow-lg"
          style={{
            left: `${Math.min(70, Math.max(2, primaryAnchor.bbox[1] / 10 - 2))}%`,
            top: `${Math.max(8, primaryAnchor.bbox[0] / 10 - 9)}%`,
          }}
        >
          {primaryAnchor.label} · {primaryAnchor.known_size_label} →{" "}
          {primaryAnchor.px_per_in.toFixed(1)} px/in (±{scaleData.tolerance_in}&quot;)
        </div>
      )}

      {/* Dragging feedback toast */}
      {draggingZoneId && dragPreviewWidth !== null && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 px-3 py-1.5 rounded-lg bg-[#0C0D10]/95 border border-[#38BDF8] text-xs font-mono tabular-nums-strict text-[#38BDF8] shadow-xl">
          Overriding {draggingZoneId} width → {dragPreviewWidth.toFixed(1)}&quot; W
          (release to re-run verify_bundle.py)
        </div>
      )}
    </div>
  );
}
