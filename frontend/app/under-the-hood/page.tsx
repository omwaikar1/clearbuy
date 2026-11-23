"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Compass,
  Cpu,
  FlaskConical,
  Layers,
  Ruler,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
} from "lucide-react";
import { BenchmarkDrawer } from "@/components/BenchmarkDrawer";
import { MOCK_BENCHMARK_DATA } from "@/lib/mockData";
import { DEFAULT_USE_MOCK, fetchBenchmarkData } from "@/lib/sseClient";
import type { BenchmarkData } from "@/types/clearbuy";

export default function UnderTheHoodPage() {
  const [proofOpen, setProofOpen] = useState(false);
  const [benchmarkData, setBenchmarkData] = useState<BenchmarkData>(
    MOCK_BENCHMARK_DATA
  );

  useEffect(() => {
    fetchBenchmarkData(DEFAULT_USE_MOCK)
      .then((d) => setBenchmarkData(d))
      .catch(() => {});
  }, []);

  return (
    <div className="min-h-screen w-full bg-at-bg text-at-ink theme-dark">
      {/* Top Bar */}
      <header className="h-12 px-4 border-b border-at-border bg-at-card flex items-center justify-between gap-3 sticky top-0 z-40">
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-2">
            <span className="h-7 w-7 rounded-lg bg-at-cyan/15 border border-at-cyan/50 flex items-center justify-center text-at-cyan">
              <Compass className="h-4 w-4" />
            </span>
            <span className="text-sm font-semibold tracking-[-0.02em] text-at-ink">
              Datum
            </span>
          </Link>
          <span className="text-xs font-mono text-at-muted">
            / under-the-hood
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setProofOpen(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-at-bg hover:border-at-emerald border border-at-border text-xs font-mono tabular-nums-strict text-at-ink transition-colors cursor-pointer"
          >
            <FlaskConical className="h-3.5 w-3.5 text-at-emerald" />
            Proof · {benchmarkData.rooms_tested} Rooms Tested
          </button>

          <Link
            href="/"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-at-bg border border-at-border hover:border-at-cyan text-xs font-medium text-at-ink transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5 text-at-cyan" />
            Back to Studio
          </Link>
        </div>
      </header>

      <main className="max-w-[1080px] mx-auto px-6 py-10 space-y-10">
        {/* Hero */}
        <div className="space-y-2.5 max-w-3xl">
          <p className="text-xs font-mono uppercase tracking-wider text-at-cyan">
            Technical Architecture · Verified Spatial Commerce Compiler
          </p>
          <h1 className="text-3xl sm:text-4xl font-semibold tracking-[-0.02em] text-at-ink">
            Under the Hood
          </h1>
          <p className="text-sm sm:text-base text-at-muted leading-relaxed">
            Datum combines a 4-model Gemini 4 pipeline, deterministic Managed
            Agents guardrails, and live Shopify Shop MCP / UCP protocols so
            every rendered item physically fits your room and is actually in
            stock.
          </p>
        </div>

        {/* 4-Stage Pipeline */}
        <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="rounded-2xl bg-at-card border border-at-border p-5 space-y-2">
            <div className="flex items-center gap-2 text-at-cyan">
              <Ruler className="h-4 w-4" />
              <span className="text-xs font-mono font-semibold">
                01 · TWO-LAYER SCALE ENGINE
              </span>
            </div>
            <h2 className="text-base font-semibold text-at-ink">
              gemini-4-neon (xhigh) + Depth-Anything-V2 + EXIF
            </h2>
            <p className="text-xs text-at-muted leading-relaxed">
              Client-side preprocessing resizes uploads to 1024px JPEG and
              extracts <code className="font-mono text-at-cyan">FocalLengthIn35mmFilm</code>{" "}
              in ~1 ms. Layer 1 calibrates pixels-per-inch from physical anchors
              (US wall outlet 4.5&quot;, door frames) with cross-anchor skew
              checking (&gt;15% warning). Layer 2 falls back to metric depth +
              EXIF pinhole geometry when no anchor is visible.
            </p>
          </div>

          <div className="rounded-2xl bg-at-card border border-at-border p-5 space-y-2">
            <div className="flex items-center gap-2 text-at-emerald">
              <ShieldCheck className="h-4 w-4" />
              <span className="text-xs font-mono font-semibold">
                02 · DETERMINISTIC GUARDRAIL
              </span>
            </div>
            <h2 className="text-base font-semibold text-at-ink">
              Managed Agents hooks.json · verify_bundle.py
            </h2>
            <p className="text-xs text-at-muted leading-relaxed">
              Before any image renders, a{" "}
              <code className="font-mono text-at-emerald">pre_tool_execution</code>{" "}
              hook validates 2D bounding-box fit, 24&quot; walkway clearance,
              and strict USD budget. Oversized SKUs return{" "}
              <code className="font-mono text-at-rose">DENY</code> with exact
              overflow math and trigger an automatic swap until{" "}
              <code className="font-mono text-at-emerald">ALLOW</code>.
            </p>
          </div>

          <div className="rounded-2xl bg-at-card border border-at-border p-5 space-y-2">
            <div className="flex items-center gap-2 text-at-notice">
              <Cpu className="h-4 w-4" />
              <span className="text-xs font-mono font-semibold">
                03 · ~200 MS DECISIONS API GATE
              </span>
            </div>
            <h2 className="text-base font-semibold text-at-ink">
              gemini-decision-1 (v1beta · 0 Output Tokens)
            </h2>
            <p className="text-xs text-at-muted leading-relaxed">
              Screens up to 15 live Shopify candidate SKUs in parallel before
              bundle selection, then audits every rendered frame across 4
              rubrics:{" "}
              <code className="font-mono text-at-ink">no_clipping</code>,{" "}
              <code className="font-mono text-at-ink">room_preserved</code>,{" "}
              <code className="font-mono text-at-ink">scale_honest</code>, and{" "}
              <code className="font-mono text-at-ink">sku_fidelity</code> (with
              1× automatic clip repair).
            </p>
          </div>

          <div className="rounded-2xl bg-at-card border border-at-border p-5 space-y-2">
            <div className="flex items-center gap-2 text-[#9D85FF]">
              <ShoppingBag className="h-4 w-4" />
              <span className="text-xs font-mono font-semibold">
                04 · STAGING &amp; LIVE SHOPIFY UCP
              </span>
            </div>
            <h2 className="text-base font-semibold text-at-ink">
              Nano Banana 2.1 + gemini-4-hydrogen + Shop MCP
            </h2>
            <p className="text-xs text-at-muted leading-relaxed">
              Direct HTTP JSON-RPC to{" "}
              <code className="font-mono text-[#9D85FF]">mcp.shop.com</code>{" "}
              (<code className="font-mono">search_catalog</code> →{" "}
              <code className="font-mono">get_product</code> →{" "}
              <code className="font-mono">create_checkout</code>) feeds exact
              product photos into 1K{" "}
              <code className="font-mono">gemini-nano-banana-2.1</code> renders
              and Shop Pay checkout links, with{" "}
              <code className="font-mono">gemini-4-hydrogen</code> handling
              low-latency voice swaps.
            </p>
          </div>
        </section>

        {/* Model Split Table */}
        <section className="rounded-2xl bg-at-card border border-at-border overflow-hidden">
          <div className="px-5 py-3.5 border-b border-at-border flex items-center gap-2">
            <Layers className="h-4 w-4 text-at-cyan" />
            <h2 className="text-sm font-semibold text-at-ink">
              Gemini 4 Model Split &amp; Latency Budget
            </h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-at-border bg-at-bg/60 font-mono text-[11px] text-at-muted">
                <tr>
                  <th className="px-5 py-2.5">Model</th>
                  <th className="px-5 py-2.5">Responsibility</th>
                  <th className="px-5 py-2.5">Key API / Mode</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-at-border">
                <tr>
                  <td className="px-5 py-3 font-mono text-at-cyan font-semibold">
                    gemini-4-neon
                  </td>
                  <td className="px-5 py-3 text-at-ink">
                    Multi-anchor scale calibration &amp; agent planning
                  </td>
                  <td className="px-5 py-3 font-mono text-at-muted">
                    xhigh thinking · 0–1000 bboxes
                  </td>
                </tr>
                <tr>
                  <td className="px-5 py-3 font-mono text-at-emerald font-semibold">
                    gemini-4-hydrogen
                  </td>
                  <td className="px-5 py-3 text-at-ink">
                    Voice &amp; text conversational swap routing
                  </td>
                  <td className="px-5 py-3 font-mono text-at-muted">
                    POST /thread · &lt;1s turn
                  </td>
                </tr>
                <tr>
                  <td className="px-5 py-3 font-mono text-[#9D85FF] font-semibold">
                    gemini-nano-banana-2.1
                  </td>
                  <td className="px-5 py-3 text-at-ink">
                    Multi-SKU room staging &amp; surgical v1 → v2 swaps
                  </td>
                  <td className="px-5 py-3 font-mono text-at-muted">
                    1K image generation + editing
                  </td>
                </tr>
                <tr>
                  <td className="px-5 py-3 font-mono text-at-notice font-semibold">
                    gemini-decision-1
                  </td>
                  <td className="px-5 py-3 text-at-ink">
                    Parallel catalog gate &amp; 4-rubric pixel QA
                  </td>
                  <td className="px-5 py-3 font-mono text-at-muted">
                    v1beta decisions.create (~200 ms)
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        {/* Streaming Endpoints */}
        <section className="rounded-2xl bg-at-card border border-at-border p-5 space-y-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-at-cyan" />
            <h2 className="text-sm font-semibold text-at-ink">
              FastAPI SSE &amp; Interaction Endpoints
            </h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 text-xs font-mono">
            <div className="rounded-lg bg-at-bg border border-at-border px-3 py-2">
              <span className="text-at-cyan">POST</span> /api/session/start → SSE
              stream
            </div>
            <div className="rounded-lg bg-at-bg border border-at-border px-3 py-2">
              <span className="text-at-emerald">PATCH</span> /api/session/&#123;id&#125;/zone
            </div>
            <div className="rounded-lg bg-at-bg border border-at-border px-3 py-2">
              <span className="text-at-cyan">POST</span> /api/session/&#123;id&#125;/thread
            </div>
            <div className="rounded-lg bg-at-bg border border-at-border px-3 py-2">
              <span className="text-at-cyan">POST</span> /api/session/&#123;id&#125;/swap
            </div>
            <div className="rounded-lg bg-at-bg border border-at-border px-3 py-2">
              <span className="text-[#9D85FF]">GET</span> /api/benchmark
            </div>
          </div>
        </section>
      </main>

      <BenchmarkDrawer
        open={proofOpen}
        onClose={() => setProofOpen(false)}
        data={benchmarkData}
      />
    </div>
  );
}
