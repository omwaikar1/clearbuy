"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Camera,
  DollarSign,
  Mic,
  MicOff,
  Ruler,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  X,
} from "lucide-react";
import type { DemoPreset, SpaceScope } from "@/types/clearbuy";
import {
  extractBudgetFromPrompt,
  preprocessRoomImage,
  type ProcessedRoomImage,
} from "@/lib/imageUtils";
import { DEMO_PRESETS, makeSunlitRoomSvg } from "@/lib/mockData";

interface CaptureCanvasProps {
  onLaunchSession: (payload: {
    images: ProcessedRoomImage[];
    prompt: string;
    budgetUsd: number;
    scope: SpaceScope;
    preset?: DemoPreset;
  }) => void;
}

interface SpeechRecognitionEventLike {
  results: {
    length: number;
    [index: number]: {
      0: { transcript: string };
      isFinal: boolean;
    };
  };
}

interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

type PreviewMode = "original" | "blueprint" | "rendered";

const SCOPE_OPTIONS: { value: SpaceScope; label: string; hint: string }[] = [
  { value: "auto", label: "Auto", hint: "Detect automatically" },
  { value: "nook", label: "Single Nook", hint: "One empty gap" },
  { value: "upgrade", label: "Setup Upgrade", hint: "Keep existing pieces" },
  { value: "full_room", label: "Full Room", hint: "Multi-zone layout" },
];

export function CaptureCanvas({ onLaunchSession }: CaptureCanvasProps) {
  const [images, setImages] = useState<ProcessedRoomImage[]>([]);
  const [activePreviewIdx, setActivePreviewIdx] = useState<number>(0);
  const [prompt, setPrompt] = useState(
    "Compact standing desk, ergonomic chair & warm lamp under $450"
  );
  const [budgetUsd, setBudgetUsd] = useState<number>(450);
  const [budgetInput, setBudgetInput] = useState<string>("450");
  const [scope, setScope] = useState<SpaceScope>("auto");
  const [previewMode, setPreviewMode] = useState<PreviewMode>("rendered");
  const [isDragging, setIsDragging] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [micDenied, setMicDenied] = useState(false);
  const [isProcessingImage, setIsProcessingImage] = useState(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    const detected = extractBudgetFromPrompt(prompt, budgetUsd);
    if (detected !== budgetUsd && detected >= 50 && detected <= 25000) {
      setBudgetUsd(detected);
      setBudgetInput(String(detected));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prompt]);

  const handleFiles = useCallback(async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;
    setIsProcessingImage(true);
    try {
      const selected = Array.from(fileList)
        .filter((f) => f.type.startsWith("image/"))
        .slice(0, 3);
      const processed = await Promise.all(
        selected.map((f) => preprocessRoomImage(f, 1024))
      );
      setImages((prev) => [...prev, ...processed].slice(0, 3));
    } finally {
      setIsProcessingImage(false);
    }
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  const startVoiceCapture = () => {
    const win = window as unknown as {
      SpeechRecognition?: new () => SpeechRecognitionLike;
      webkitSpeechRecognition?: new () => SpeechRecognitionLike;
    };
    const SpeechRec = win.SpeechRecognition || win.webkitSpeechRecognition;
    if (!SpeechRec) {
      setMicDenied(true);
      return;
    }
    try {
      const rec = new SpeechRec();
      rec.continuous = true;
      rec.interimResults = true;
      rec.lang = "en-US";
      rec.onresult = (event) => {
        let transcript = "";
        for (let i = 0; i < event.results.length; i++) {
          transcript += event.results[i][0].transcript;
        }
        if (transcript.trim()) setPrompt(transcript.trim());
      };
      rec.onerror = () => {
        setMicDenied(true);
        setIsListening(false);
      };
      rec.onend = () => setIsListening(false);
      recognitionRef.current = rec;
      rec.start();
      setIsListening(true);
    } catch {
      setMicDenied(true);
    }
  };

  const stopVoiceCapture = () => {
    recognitionRef.current?.stop();
    setIsListening(false);
  };

  const handleRunPreset = (preset: DemoPreset) => {
    onLaunchSession({
      images: [],
      prompt: preset.prompt,
      budgetUsd: preset.budget_usd,
      scope: preset.scope,
      preset,
    });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (images.length === 0) {
      handleRunPreset({
        ...DEMO_PRESETS[0],
        prompt: prompt.trim() || DEMO_PRESETS[0].prompt,
        budget_usd: budgetUsd,
        scope: scope === "auto" ? DEMO_PRESETS[0].scope : scope,
      });
      return;
    }
    onLaunchSession({
      images,
      prompt: prompt.trim() || DEMO_PRESETS[0].prompt,
      budgetUsd,
      scope,
    });
  };

  const heroExampleImg = makeSunlitRoomSvg({
    vibe: "scandi",
    rendered: previewMode === "rendered",
  });

  return (
    <div
      className="h-[calc(100vh-48px)] w-full bg-architectural-grid overflow-y-auto px-6 py-8"
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        multiple
        capture="environment"
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />

      <div className="max-w-[1120px] mx-auto space-y-6">
        {/* Centered Editorial Headline */}
        <div className="text-center space-y-2 max-w-3xl mx-auto">
          <h1 className="text-4xl sm:text-5xl font-semibold tracking-[-0.02em] text-at-ink leading-tight">
            See real furniture in your exact room.
          </h1>
          <p className="text-base text-at-muted leading-relaxed">
            Drop 1–3 room photos and describe your style &amp; budget. ClearBuy
            measures your space, checks fit &amp; budget, and shows real furniture
            you can buy.
          </p>
        </div>

        {/* Centered Wide Room Showcase Card + Unified Single Horizontal Pill Bar */}
        <div
          className={`rounded-2xl overflow-hidden bg-at-card border shadow-xl transition-all ${
            isDragging
              ? "border-at-cyan ring-2 ring-at-cyan/30 scale-[1.005]"
              : "border-at-border"
          }`}
        >
          {/* Card Top Strip: Status / Guide Label */}
          <div className="px-5 py-2.5 border-b border-at-border flex items-center justify-between gap-2.5">
            {images.length === 0 ? (
              <div className="flex items-center gap-2 text-xs text-at-muted">
                <span className="h-2 w-2 rounded-full bg-at-cyan" />
                <span className="text-at-ink font-medium">Your Room</span>
                <span>· Drop photos or preview an example</span>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-xs font-mono text-at-emerald">
                <span>
                  {images.length}/3 Room Angle{images.length > 1 ? "s" : ""} Ready
                </span>
              </div>
            )}
          </div>

          {/* Interactive Dropzone + 3-Step Product Walkthrough OR User's Uploaded Room Photo */}
          <div
            className={`relative w-full bg-at-bg overflow-hidden ${
              images.length === 0 ? "min-h-[340px]" : "aspect-[16/9]"
            }`}
          >
            {isProcessingImage && (
              <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/30 backdrop-blur-xs">
                <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-at-card border border-at-border text-xs font-mono text-at-ink shadow-lg">
                  <Sparkles className="h-4 w-4 text-at-cyan animate-spin" />
                  Optimizing to 1024px &amp; reading EXIF…
                </div>
              </div>
            )}

            {images.length === 0 ? (
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 p-6 items-stretch">
                {/* Left: Tactile Photo Dropzone */}
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="lg:col-span-5 relative rounded-xl border-2 border-dashed border-at-border hover:border-at-cyan bg-at-card/60 hover:bg-at-card p-6 flex flex-col items-center justify-center text-center gap-3 transition-all cursor-pointer group"
                >
                  <span className="absolute top-3 left-3 h-3 w-3 border-t-2 border-l-2 border-at-cyan/60 rounded-tl-xs" />
                  <span className="absolute top-3 right-3 h-3 w-3 border-t-2 border-r-2 border-at-cyan/60 rounded-tr-xs" />
                  <span className="absolute bottom-3 left-3 h-3 w-3 border-b-2 border-l-2 border-at-cyan/60 rounded-bl-xs" />
                  <span className="absolute bottom-3 right-3 h-3 w-3 border-b-2 border-r-2 border-at-cyan/60 rounded-br-xs" />

                  <div className="h-12 w-12 rounded-full bg-at-cyan/10 border border-at-cyan/30 flex items-center justify-center text-at-cyan group-hover:scale-105 transition-transform">
                    <Camera className="h-5 w-5" />
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm font-semibold text-at-ink">
                      Drop 1–3 room photos here
                    </p>
                    <p className="text-xs text-at-muted">
                      Click to browse or take a photo on mobile
                    </p>
                  </div>
                  <div className="inline-flex items-center gap-2 text-[11px] text-at-cyan bg-at-cyan/10 border border-at-cyan/20 px-2.5 py-1 rounded-full">
                    Supports 1–3 room angles
                  </div>

                  {/* Visual Furniture Silhouettes */}
                  <div className="w-full pt-3 mt-1 border-t border-at-border/70 grid grid-cols-3 gap-2">
                    <div className="rounded-lg bg-at-bg/80 border border-at-border px-2 py-2 flex flex-col items-center gap-1">
                      <svg viewBox="0 0 48 32" className="w-8 h-5 text-at-cyan" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <rect x="4" y="8" width="40" height="4" rx="1" />
                        <line x1="9" y1="12" x2="9" y2="28" />
                        <line x1="39" y1="12" x2="39" y2="28" />
                        <line x1="12" y1="19" x2="36" y2="19" strokeOpacity="0.45" strokeDasharray="2 2" />
                      </svg>
                      <span className="text-[10px] font-mono text-at-ink">Desk · 40&quot;</span>
                    </div>
                    <div className="rounded-lg bg-at-bg/80 border border-at-border px-2 py-2 flex flex-col items-center gap-1">
                      <svg viewBox="0 0 48 32" className="w-8 h-5 text-at-emerald" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M16 6h16v10H16z" />
                        <path d="M14 16h20v4H14z" />
                        <line x1="24" y1="20" x2="24" y2="27" />
                        <line x1="16" y1="27" x2="32" y2="27" />
                      </svg>
                      <span className="text-[10px] font-mono text-at-ink">Chair · 25&quot;</span>
                    </div>
                    <div className="rounded-lg bg-at-bg/80 border border-at-border px-2 py-2 flex flex-col items-center gap-1">
                      <svg viewBox="0 0 48 32" className="w-8 h-5 text-at-notice" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M17 12l3-7h8l3 7z" />
                        <line x1="24" y1="12" x2="24" y2="27" />
                        <line x1="17" y1="27" x2="31" y2="27" />
                      </svg>
                      <span className="text-[10px] font-mono text-at-ink">Lamp · 14&quot;</span>
                    </div>
                  </div>
                </button>

                {/* Right: Sample Room Interactive Preview + 3-Step Walkthrough */}
                <div className="lg:col-span-7 flex flex-col gap-3">
                  {/* Interactive Sample Room Preview */}
                  <div className="relative rounded-xl overflow-hidden border border-at-border bg-at-card aspect-[16/8]">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={heroExampleImg}
                      alt="Sample room preview"
                      className="w-full h-full object-cover transition-all duration-300"
                    />
                    {previewMode === "blueprint" && (
                      <svg
                        viewBox="0 0 1000 660"
                        preserveAspectRatio="none"
                        className="absolute inset-0 w-full h-full pointer-events-none"
                      >
                        <rect
                          x="200"
                          y="376"
                          width="30"
                          height="42"
                          rx="4"
                          fill="rgba(56,189,248,0.16)"
                          stroke="#38BDF8"
                          strokeWidth="2.5"
                          strokeDasharray="6 4"
                        />
                        <line
                          x1="230"
                          y1="397"
                          x2="262"
                          y2="397"
                          stroke="#38BDF8"
                          strokeWidth="2"
                          strokeDasharray="5 4"
                        />
                        <rect
                          x="262"
                          y="302"
                          width="358"
                          height="234"
                          rx="6"
                          fill="rgba(56,189,248,0.08)"
                          stroke="#38BDF8"
                          strokeWidth="2.5"
                        />
                        <line
                          x1="262"
                          y1="274"
                          x2="620"
                          y2="274"
                          stroke="#38BDF8"
                          strokeWidth="2.5"
                        />
                        <rect
                          x="366"
                          y="256"
                          width="150"
                          height="34"
                          rx="8"
                          fill="#0C0D10"
                          fillOpacity="0.92"
                        />
                        <text
                          x="441"
                          y="278"
                          textAnchor="middle"
                          fill="#38BDF8"
                          fontSize="16"
                          fontFamily="monospace"
                          fontWeight="600"
                        >
                          Z1 · 43.5&quot; W
                        </text>
                      </svg>
                    )}

                    {/* Floating Mode Toggle + Caption */}
                    <div className="absolute top-2.5 left-2.5 right-2.5 flex items-center justify-between gap-2">
                      <span className="px-2.5 py-1 rounded-full bg-at-card/90 backdrop-blur border border-at-border text-[11px] font-mono text-at-muted">
                        Example Output
                      </span>
                      <div className="flex items-center gap-0.5 p-0.5 rounded-lg bg-at-card/90 backdrop-blur border border-at-border text-[11px]">
                        {(["original", "blueprint", "rendered"] as PreviewMode[]).map(
                          (mode) => (
                            <button
                              key={mode}
                              type="button"
                              onClick={() => setPreviewMode(mode)}
                              className={`px-2 py-0.5 rounded-md font-medium capitalize transition-all cursor-pointer ${
                                previewMode === mode
                                  ? "bg-at-cyan text-[#0C0D10] font-semibold"
                                  : "text-at-muted hover:text-at-ink"
                              }`}
                            >
                              {mode}
                            </button>
                          )
                        )}
                      </div>
                    </div>
                  </div>

                  {/* 3-Step Product Walkthrough */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                    <div className="rounded-xl bg-at-card border border-at-border px-3 py-2.5 flex items-center gap-2.5">
                      <div className="h-7 w-7 rounded-lg bg-at-cyan/10 border border-at-cyan/30 flex items-center justify-center text-at-cyan shrink-0">
                        <Ruler className="h-3.5 w-3.5" />
                      </div>
                      <div className="min-w-0">
                        <p className="text-[11px] font-semibold text-at-cyan">
                          1. Measure
                        </p>
                        <p className="text-xs font-medium text-at-ink truncate">
                          Auto-scaled to room
                        </p>
                      </div>
                    </div>

                    <div className="rounded-xl bg-at-card border border-at-border px-3 py-2.5 flex items-center gap-2.5">
                      <div className="h-7 w-7 rounded-lg bg-at-emerald/10 border border-at-emerald/30 flex items-center justify-center text-at-emerald shrink-0">
                        <ShieldCheck className="h-3.5 w-3.5" />
                      </div>
                      <div className="min-w-0">
                        <p className="text-[11px] font-semibold text-at-emerald">
                          2. Fit Check
                        </p>
                        <p className="text-xs font-medium text-at-ink truncate">
                          Wall &amp; budget safe
                        </p>
                      </div>
                    </div>

                    <div className="rounded-xl bg-at-card border border-at-border px-3 py-2.5 flex items-center gap-2.5">
                      <div className="h-7 w-7 rounded-lg bg-[#5A31F4]/15 border border-[#5A31F4]/40 flex items-center justify-center text-[#9D85FF] shrink-0">
                        <ShoppingBag className="h-3.5 w-3.5" />
                      </div>
                      <div className="min-w-0">
                        <p className="text-[11px] font-semibold text-[#9D85FF]">
                          3. Shop Direct
                        </p>
                        <p className="text-xs font-medium text-at-ink truncate">
                          Real in-stock items
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="relative w-full h-[380px] sm:h-[420px] bg-at-bg flex items-center justify-center">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={(images[activePreviewIdx] ?? images[0]).previewUrl}
                  alt="Your uploaded room"
                  className="max-h-full max-w-full object-contain"
                />
                <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    {images.map((img, idx) => (
                      <div
                        key={img.previewUrl}
                        onClick={() => setActivePreviewIdx(idx)}
                        className={`relative h-14 w-20 rounded-lg overflow-hidden border-2 shadow-lg cursor-pointer transition-all ${
                          idx === activePreviewIdx
                            ? "border-at-cyan ring-2 ring-at-cyan/40"
                            : "border-at-card opacity-80 hover:opacity-100"
                        }`}
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={img.previewUrl}
                          alt={`Angle ${idx + 1}`}
                          className="h-full w-full object-cover"
                        />
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setImages((prev) => {
                              const next = prev.filter((_, i) => i !== idx);
                              setActivePreviewIdx((cur) =>
                                Math.max(0, Math.min(cur, next.length - 1))
                              );
                              return next;
                            });
                          }}
                          className="absolute top-0.5 right-0.5 p-0.5 rounded-full bg-black/70 text-white cursor-pointer"
                          aria-label="Remove photo"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </div>
                    ))}
                    {images.length < 3 && (
                      <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        className="h-14 px-3 rounded-lg bg-at-card/90 backdrop-blur border border-at-border text-xs font-medium text-at-ink hover:border-at-cyan cursor-pointer"
                      >
                        + Angle
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Unified Single Horizontal Pill Bar (Speak · Prompt · Budget · Design) */}
          <form
            onSubmit={handleSubmit}
            className="px-5 py-4 border-t border-at-border bg-at-card space-y-2.5"
          >
            <div className="flex items-center gap-2 rounded-full bg-at-bg border border-at-border p-2 pl-2.5 shadow-xs">
              <button
                type="button"
                onMouseDown={startVoiceCapture}
                onMouseUp={stopVoiceCapture}
                onMouseLeave={() => isListening && stopVoiceCapture()}
                onTouchStart={startVoiceCapture}
                onTouchEnd={stopVoiceCapture}
                title={
                  micDenied
                    ? "Mic unavailable — type your request"
                    : "Hold to speak your request"
                }
                className={`h-11 w-11 rounded-full border inline-flex items-center justify-center shrink-0 cursor-pointer transition-all ${
                  isListening
                    ? "bg-at-cyan/15 border-at-cyan text-at-cyan"
                    : "bg-at-card border-at-border hover:border-at-cyan text-at-cyan"
                }`}
              >
                {micDenied ? (
                  <MicOff className="h-4 w-4 text-at-notice" />
                ) : isListening ? (
                  <span className="flex items-center gap-0.5 h-4">
                    {[0, 1, 2].map((bar) => (
                      <span
                        key={bar}
                        className="w-0.5 h-full bg-at-cyan rounded-full animate-clearbuy-wave"
                        style={{ animationDelay: `${bar * 120}ms` }}
                      />
                    ))}
                  </span>
                ) : (
                  <Mic className="h-4 w-4" />
                )}
              </button>

              <div className="h-6 w-px bg-at-border mx-1 shrink-0" />

              <input
                type="text"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Describe what you want (e.g., Standing desk, chair & warm lamp under $450)"
                className="flex-1 bg-transparent text-sm sm:text-base text-at-ink placeholder:text-at-muted focus:outline-none min-w-0 px-1"
              />

              <div className="h-6 w-px bg-at-border mx-1 shrink-0" />

              <label
                title="Maximum budget (USD)"
                className="h-11 px-3.5 rounded-full bg-at-card border border-at-border inline-flex items-center gap-1 text-sm font-mono tabular-nums-strict text-at-emerald shrink-0"
              >
                <DollarSign className="h-4 w-4" />
                <input
                  type="text"
                  inputMode="numeric"
                  value={budgetInput}
                  onChange={(e) => {
                    const digits = e.target.value.replace(/\D/g, "");
                    setBudgetInput(digits);
                    const n = Number(digits);
                    if (n > 0) setBudgetUsd(n);
                  }}
                  onBlur={() => {
                    const clamped = Math.min(
                      25000,
                      Math.max(50, Number(budgetInput) || 450)
                    );
                    setBudgetUsd(clamped);
                    setBudgetInput(String(clamped));
                  }}
                  className="w-14 bg-transparent font-semibold text-at-ink focus:outline-none"
                />
              </label>

              <button
                type="submit"
                className="h-11 px-5 rounded-full bg-at-cyan hover:opacity-95 text-[#0C0D10] text-sm font-semibold inline-flex items-center gap-2 shrink-0 cursor-pointer transition-transform active:scale-95"
              >
                <span>Design</span>
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>

            {/* Scope Chip Selector Below Search Bar */}
            <div className="flex flex-wrap items-center justify-center gap-2 pt-0.5 px-1">
              <div className="flex items-center gap-1.5 flex-wrap justify-center">
                <span className="text-xs font-mono text-at-muted">Scope:</span>
                <div className="flex items-center gap-1.5 p-1 rounded-xl bg-at-bg border border-at-border flex-wrap justify-center">
                  {SCOPE_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setScope(opt.value)}
                      className={`px-3 py-1 rounded-lg text-left transition-colors cursor-pointer flex items-center gap-1.5 ${
                        scope === opt.value
                          ? "bg-at-card text-at-ink border border-at-cyan/50 shadow-xs"
                          : "text-at-muted hover:text-at-ink border border-transparent"
                      }`}
                    >
                      <span className="text-xs font-medium">{opt.label}</span>
                      <span className="text-[11px] opacity-70">· {opt.hint}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </form>
        </div>

        {/* 3 Sample Room Presets Below */}
        <div className="space-y-2.5 pb-6">
          <p className="text-sm font-medium text-center text-at-muted">
            Or launch a one-click demo preset
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
            {DEMO_PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                onClick={() => handleRunPreset(preset)}
                className="group text-left rounded-xl p-4 bg-at-card border border-at-border hover:border-at-cyan transition-all flex items-center gap-3.5 shadow-xs cursor-pointer"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={preset.rendered_image_url}
                  alt={preset.title}
                  className="h-16 w-20 rounded-lg object-cover border border-at-border shrink-0"
                />
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-at-ink group-hover:text-at-cyan transition-colors truncate">
                    {preset.title}
                  </p>
                  <p className="text-xs text-at-muted truncate mt-0.5">
                    {preset.subtitle}
                  </p>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Bottom Footer Link to Technical Details */}
        <div className="pt-2 pb-6 flex justify-center">
          <Link
            href="/under-the-hood"
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-at-card border border-at-border hover:border-at-cyan text-xs text-at-muted hover:text-at-ink transition-colors"
          >
            <span>Under the Hood</span>
            <ArrowRight className="h-3.5 w-3.5 text-at-cyan" />
          </Link>
        </div>
      </div>
    </div>
  );
}
