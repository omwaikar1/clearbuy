"use client";

import React, { useState } from "react";
import {
  AlertTriangle,
  Award,
  CheckCircle2,
  FlaskConical,
  Wrench,
  X,
} from "lucide-react";
import type { BenchmarkData } from "@/types/clearbuy";
import { API_BASE_URL } from "@/lib/sseClient";

interface BenchmarkDrawerProps {
  open: boolean;
  onClose: () => void;
  data: BenchmarkData;
}

export function BenchmarkDrawer({ open, onClose, data }: BenchmarkDrawerProps) {
  const [selectedRoomId, setSelectedRoomId] = useState<string>(
    data.room_samples[0]?.room_id ?? ""
  );
  const [failedThumbIds, setFailedThumbIds] = useState<Record<string, boolean>>({});

  if (!open) return null;

  const selectedRoom =
    data.room_samples.find((r) => r.room_id === selectedRoomId) ||
    data.room_samples[0];

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/65 backdrop-blur-xs">
      <div className="w-full max-w-2xl h-full bg-at-card border-l border-at-border shadow-2xl flex flex-col overflow-hidden">
        {/* Drawer Header */}
        <div className="px-5 py-4 border-b border-at-border flex items-center justify-between shrink-0">
          <div className="space-y-0.5">
            <div className="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-wider text-at-emerald">
              <FlaskConical className="h-3.5 w-3.5" />5 Sigma Proof Layer ·{" "}
              {data.rooms_tested} Rooms Tested
            </div>
            <h2 className="text-base font-semibold text-at-ink">
              {data.dataset_label}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-at-bg text-at-muted cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-6">
          {/* 1. 3-Way Evaluation Table (including Visual QA Pass % column) */}
          <section className="space-y-2.5">
            <h3 className="text-xs font-mono uppercase tracking-wider text-at-muted">
              1. 3-Way Quantitative Benchmark (Pixel-Exact Kinect Ground Truth)
            </h3>
            <div className="rounded-xl border border-at-border overflow-x-auto bg-at-bg">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-at-border text-[10px] font-mono uppercase text-at-micro">
                    <th className="py-2.5 px-3">Pipeline</th>
                    <th className="py-2.5 px-2 text-right">Real SKUs</th>
                    <th className="py-2.5 px-2 text-right">Fit Pass</th>
                    <th className="py-2.5 px-2 text-right">Budget</th>
                    <th className="py-2.5 px-2 text-right">Visual QA</th>
                    <th className="py-2.5 px-3 text-right">Scale Err</th>
                  </tr>
                </thead>
                <tbody className="font-mono tabular-nums-strict divide-y divide-at-border">
                  {data.comparison_rows.map((row, i) => {
                    const isOurs = i === data.comparison_rows.length - 1;
                    return (
                      <tr
                        key={row.method}
                        className={
                          isOurs ? "bg-at-emerald/10 text-at-ink" : "text-at-muted"
                        }
                      >
                        <td className="py-2.5 px-3 font-sans font-medium">
                          {row.method}
                        </td>
                        <td className="py-2.5 px-2 text-right">
                          {row.real_buyable_sku_pct.toFixed(0)}%
                        </td>
                        <td
                          className={`py-2.5 px-2 text-right ${
                            isOurs ? "text-at-emerald font-semibold" : ""
                          }`}
                        >
                          {row.physical_fit_pass_pct.toFixed(1)}%
                        </td>
                        <td
                          className={`py-2.5 px-2 text-right ${
                            isOurs ? "text-at-emerald font-semibold" : ""
                          }`}
                        >
                          {row.budget_compliance_pct.toFixed(1)}%
                        </td>
                        <td
                          className={`py-2.5 px-2 text-right ${
                            isOurs ? "text-at-emerald font-semibold" : ""
                          }`}
                        >
                          {row.visual_qa_pass_pct.toFixed(1)}%
                        </td>
                        <td className="py-2.5 px-3 text-right text-at-cyan">
                          {row.median_scale_err_in}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {/* 2. Gemini 4 Thinking-Level Ablation + Decisions QA Catch Rate */}
          <section className="space-y-2.5">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <h3 className="text-xs font-mono uppercase tracking-wider text-at-muted">
                2. Gemini 4 Thinking-Level Ablation (Neon low vs. xhigh)
              </h3>
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-at-cyan/15 text-[11px] font-mono tabular-nums-strict text-at-cyan">
                <Award className="h-3 w-3" />
                Decisions QA Catch Rate: {data.qa_catch_rate_pct}%
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              {data.ablation_rows.map((ab, idx) => (
                <div
                  key={ab.model_config}
                  className={`rounded-xl p-3 bg-at-bg border space-y-1.5 ${
                    idx === 1 ? "border-at-cyan/50" : "border-at-border"
                  }`}
                >
                  <p className="text-xs font-mono text-at-ink">{ab.model_config}</p>
                  <div className="flex items-center justify-between text-[11px] font-mono tabular-nums-strict text-at-muted">
                    <span>Multi-Anchor Err</span>
                    <span className="text-at-cyan">{ab.multi_anchor_err_in}</span>
                  </div>
                  <div className="flex items-center justify-between text-[11px] font-mono tabular-nums-strict text-at-muted">
                    <span>4–5 Item Bundle Pass</span>
                    <span className={idx === 1 ? "text-at-emerald" : "text-at-notice"}>
                      {ab.coupled_bundle_pass_pct}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* 3. Clickable Room Filmstrip with Photo Thumbnails */}
          <section className="space-y-2.5">
            <h3 className="text-xs font-mono uppercase tracking-wider text-at-muted">
              3. Per-Room Kinect Ground-Truth Inspection
            </h3>
            <div className="flex gap-2.5 overflow-x-auto pb-1.5">
              {data.room_samples.map((room) => {
                const thumbSrc =
                  room.image_url ||
                  `${API_BASE_URL}/api/benchmark/assets/${room.room_id}_rgb.jpg`;
                const thumbBroken = Boolean(failedThumbIds[room.room_id]);
                return (
                  <button
                    key={room.room_id}
                    type="button"
                    onClick={() => setSelectedRoomId(room.room_id)}
                    className={`w-40 rounded-xl border text-left shrink-0 overflow-hidden transition-all cursor-pointer ${
                      selectedRoom?.room_id === room.room_id
                        ? "bg-at-cyan/12 border-at-cyan text-at-ink"
                        : "bg-at-bg border-at-border text-at-muted hover:border-at-cyan/50"
                    }`}
                  >
                    {!thumbBroken && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={thumbSrc}
                        alt={room.room_label}
                        onError={() =>
                          setFailedThumbIds((prev) => ({
                            ...prev,
                            [room.room_id]: true,
                          }))
                        }
                        className="h-20 w-full object-cover border-b border-at-border"
                      />
                    )}
                    <div className="p-2">
                      <p className="text-xs font-medium truncate">{room.room_label}</p>
                      <p className="text-[10px] font-mono tabular-nums-strict text-at-cyan">
                        {room.room_id} · ±{room.error_in.toFixed(1)}&quot;
                      </p>
                    </div>
                  </button>
                );
              })}
            </div>

            {selectedRoom && (
              <div className="rounded-xl p-3.5 bg-at-bg border border-at-border space-y-2 font-mono text-xs tabular-nums-strict">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-at-ink font-sans font-semibold">
                    {selectedRoom.room_label} ({selectedRoom.room_id})
                  </span>
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-at-emerald/15 text-at-emerald text-[10px]">
                    <CheckCircle2 className="h-3 w-3" />
                    {selectedRoom.calibration_layer}
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2 pt-1">
                  <div className="p-2 rounded-lg bg-at-card border border-at-border">
                    <p className="text-[10px] text-at-micro">Kinect GT Width</p>
                    <p className="text-sm text-at-ink">
                      {selectedRoom.kinect_gt_width_in.toFixed(1)}&quot;
                    </p>
                  </div>
                  <div className="p-2 rounded-lg bg-at-card border border-at-border">
                    <p className="text-[10px] text-at-micro">ClearBuy Estimate</p>
                    <p className="text-sm text-at-cyan">
                      {selectedRoom.clearbuy_est_width_in.toFixed(1)}&quot;
                    </p>
                  </div>
                  <div className="p-2 rounded-lg bg-at-card border border-at-border">
                    <p className="text-[10px] text-at-micro">Abs Error</p>
                    <p className="text-sm text-at-emerald">
                      ±{selectedRoom.error_in.toFixed(1)}&quot;
                    </p>
                  </div>
                </div>
                <p className="text-[11px] font-sans text-at-muted">
                  Chosen: <span className="text-at-ink">{selectedRoom.chosen_sku}</span>
                  {selectedRoom.blocked_sku && (
                    <>
                      {" "}
                      · Blocked:{" "}
                      <span className="text-at-coral">{selectedRoom.blocked_sku}</span>
                    </>
                  )}
                </p>
                <p className="text-[11px] font-sans text-at-micro">
                  {selectedRoom.note}
                </p>
              </div>
            )}
          </section>

          {/* 4. Honest "Where It Still Breaks" Audit */}
          <section className="space-y-2.5">
            <h3 className="text-xs font-mono uppercase tracking-wider text-at-notice flex items-center gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5" />
              4. Honest Failure Audit — Real Bugs Caught &amp; Fixed During Eval
            </h3>
            <div className="space-y-2">
              {data.failure_audits.map((item) => (
                <div
                  key={item.id}
                  className="rounded-xl p-3 bg-at-bg border border-at-border space-y-1.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-medium text-at-ink">{item.title}</p>
                    <span className="px-1.5 py-0.5 rounded bg-at-card border border-at-border text-[10px] font-mono text-at-muted">
                      {item.room_ref}
                    </span>
                  </div>
                  <p className="text-[11px] text-at-coral/90">
                    Broke: {item.what_broke}
                  </p>
                  <p className="text-[11px] text-at-emerald flex items-start gap-1.5">
                    <Wrench className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                    <span>Fixed: {item.how_we_fixed_it}</span>
                  </p>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
