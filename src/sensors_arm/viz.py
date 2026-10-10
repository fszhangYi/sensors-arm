"""Arm-only FastAPI UI (DCS teal/lab style, multi-arm)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from sensors_arm.paths import static_dir
from sensors_arm.runtime import Orchestrator

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark" data-density="comfortable">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>sensors-arm</title>
  <link rel="icon" href="/assets/favicon.svg" type="image/svg+xml"/>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet"/>
  <link rel="stylesheet" href="/assets/appearance.css"/>
  <script src="/assets/vendor/three.min.js"></script>
  <script src="/assets/vendor/OrbitControls.js"></script>
  <script src="/assets/vendor/STLLoader.js"></script>
  <script src="/assets/vendor/URDFLoader.js"></script>
  <style>
    :root {
      --bg: #0b1018;
      --bg-deep: #070c14;
      --panel: rgba(18, 28, 42, 0.78);
      --panel-solid: rgba(22, 32, 48, 0.96);
      --border: rgba(120, 160, 200, 0.16);
      --border-strong: rgba(61, 214, 198, 0.42);
      --text: #e8eef7;
      --muted: #8b9bb4;
      --accent: #3dd6c6;
      --accent-dim: rgba(61, 214, 198, 0.14);
      --spark: #f0b429;
      --danger: #f07178;
      --ok: #7fd99a;
      --chrome: rgba(12, 18, 30, 0.82);
      --brand-title: linear-gradient(120deg, #e8eef7 18%, #3dd6c6 58%, #f0b429 96%);
      --shadow-panel: 0 10px 32px rgba(0, 0, 0, 0.34), inset 0 1px 0 rgba(255, 255, 255, 0.04);
      --shadow-btn: 0 1px 0 rgba(255, 255, 255, 0.06) inset, 0 2px 8px rgba(0, 0, 0, 0.22);
      --ease: cubic-bezier(0.22, 1, 0.36, 1);
      --scrollbar-thumb: rgba(61, 214, 198, 0.38);
      --scrollbar-thumb-hover: rgba(61, 214, 198, 0.68);
      --scrollbar-size: 5px;
    }
    * { box-sizing: border-box; }
    html, body {
      height: 100%;
      margin: 0;
      overflow: hidden;
    }
    html {
      scrollbar-width: thin;
      scrollbar-color: var(--scrollbar-thumb) transparent;
    }
    *::-webkit-scrollbar {
      width: var(--scrollbar-size);
      height: var(--scrollbar-size);
    }
    *::-webkit-scrollbar-track {
      background: transparent;
      margin: 4px;
    }
    *::-webkit-scrollbar-thumb {
      background: linear-gradient(180deg, rgba(61,214,198,0.55), rgba(61,214,198,0.28));
      border-radius: 99px;
      border: 1px solid transparent;
      background-clip: padding-box;
      min-height: 28px;
    }
    *::-webkit-scrollbar-thumb:hover {
      background: linear-gradient(180deg, rgba(61,214,198,0.85), rgba(240,180,41,0.45));
    }
    *::-webkit-scrollbar-corner { background: transparent; }
    body {
      display: flex;
      flex-direction: column;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      font-feature-settings: "ss01" 1, "kern" 1;
      color: var(--text);
      background:
        radial-gradient(1100px 520px at 8% -8%, rgba(61,214,198,0.14), transparent 58%),
        radial-gradient(900px 480px at 96% 0%, rgba(240,180,41,0.09), transparent 52%),
        radial-gradient(700px 400px at 50% 110%, rgba(61,214,198,0.05), transparent 60%),
        var(--bg);
    }
    body::before {
      content: "";
      position: fixed; inset: 0; pointer-events: none; z-index: 0;
      background-image:
        linear-gradient(rgba(120,160,200,0.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(120,160,200,0.035) 1px, transparent 1px);
      background-size: 48px 48px;
      mask-image: radial-gradient(ellipse 70% 60% at 50% 30%, #000 20%, transparent 75%);
      opacity: 0.55;
    }
    header, main, #toast { position: relative; z-index: 1; }
    header {
      flex: 0 0 auto;
      display: flex; align-items: center; justify-content: space-between; gap: 1rem;
      padding: 0.7rem 1.35rem;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(180deg, rgba(18,26,40,0.92), var(--chrome));
      backdrop-filter: blur(14px) saturate(1.15);
      box-shadow: 0 1px 0 rgba(61,214,198,0.06);
    }
    .brand {
      font-size: 1.42rem; font-weight: 700; letter-spacing: 0.01em;
      background: var(--brand-title); -webkit-background-clip: text; background-clip: text;
      color: transparent;
    }
    .meta { color: var(--muted); font-size: 0.8rem; margin-top: 0.15rem; letter-spacing: 0.02em; }
    .pill {
      display: inline-flex; align-items: center; gap: 0.35rem;
      border: 1px solid rgba(61,214,198,0.28);
      border-radius: 999px;
      padding: 0.22rem 0.75rem;
      background: linear-gradient(180deg, rgba(61,214,198,0.14), rgba(61,214,198,0.05));
      color: var(--accent);
      font-size: 0.75rem; font-weight: 500; letter-spacing: 0.03em;
      box-shadow: var(--shadow-btn);
    }
    .pill.warn {
      color: var(--spark);
      border-color: rgba(240,180,41,0.35);
      background: linear-gradient(180deg, rgba(240,180,41,0.16), rgba(240,180,41,0.05));
    }
    main {
      flex: 1 1 auto;
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(220px, 280px) minmax(0, 1fr) minmax(280px, 340px);
      gap: 0.95rem;
      padding: 0.9rem 1.05rem 1rem;
      max-width: 1640px;
      width: 100%;
      margin: 0 auto;
      overflow: hidden;
    }
    @media (max-width: 1100px) {
      main {
        grid-template-columns: 1fr;
        grid-template-rows: minmax(120px, 22vh) minmax(0, 1fr) minmax(160px, 28vh);
        overflow-y: auto;
      }
      #stageWrap { min-height: 280px; }
    }
    .panel {
      background:
        linear-gradient(165deg, rgba(32, 46, 66, 0.55) 0%, transparent 42%),
        var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 0.95rem 1.05rem;
      box-shadow: var(--shadow-panel);
      backdrop-filter: blur(12px);
      min-height: 0;
      overflow: auto;
      scrollbar-gutter: stable;
    }
    .panel h2 {
      margin: 0 0 0.65rem;
      font-size: 0.72rem; font-weight: 600;
      color: var(--accent);
      letter-spacing: 0.12em;
      text-transform: uppercase;
      display: flex; align-items: center; gap: 0.5rem;
    }
    .panel h2::after {
      content: "";
      flex: 1 1 auto;
      height: 1px;
      background: linear-gradient(90deg, rgba(61,214,198,0.35), transparent);
    }
    .arm-tab {
      display: block; width: 100%; text-align: left;
      margin: 0 0 0.5rem; padding: 0.7rem 0.8rem;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: linear-gradient(180deg, rgba(255,255,255,0.03), transparent);
      color: var(--text); cursor: pointer;
      transition: border-color 0.18s var(--ease), background 0.18s var(--ease),
        transform 0.18s var(--ease), box-shadow 0.18s var(--ease);
    }
    .arm-tab:hover {
      border-color: rgba(61,214,198,0.35);
      background: rgba(61,214,198,0.07);
      transform: translateY(-1px);
    }
    .arm-tab.active {
      border-color: var(--border-strong);
      background: linear-gradient(135deg, rgba(61,214,198,0.16), rgba(61,214,198,0.05));
      box-shadow: 0 0 0 1px rgba(61,214,198,0.08), 0 6px 18px rgba(0,0,0,0.2);
    }
    .arm-tab .sub { display: block; color: var(--muted); font-size: 0.74rem; margin-top: 0.25rem; }
    .arm-tab .conn-dot {
      display: inline-block; width: 0.5rem; height: 0.5rem; border-radius: 50%;
      margin-right: 0.4rem; background: rgba(139,155,180,0.7); vertical-align: middle;
      box-shadow: 0 0 0 2px rgba(139,155,180,0.15);
    }
    .arm-tab .conn-dot.on {
      background: var(--ok);
      box-shadow: 0 0 0 2px rgba(127,217,154,0.2), 0 0 10px rgba(127,217,154,0.55);
    }
    .conn-row { margin: 0.55rem 0 0.65rem; }
    .copy-row { margin: 0.4rem 0 0.65rem; }
    .copy-row .hint { margin: 0; align-self: center; color: var(--accent); font-size: 0.72rem; }
    .ip-row {
      display: flex; align-items: baseline; gap: 0.5rem;
      margin: 0.15rem 0 0.55rem;
      padding: 0.45rem 0.6rem;
      border-radius: 10px;
      border: 1px solid rgba(120,160,200,0.16);
      background: rgba(0,0,0,0.22);
    }
    .ip-row .k {
      flex: 0 0 auto;
      color: var(--muted);
      font-size: 0.68rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }
    .ip-row .v {
      flex: 1 1 auto;
      margin: 0;
      border: 0;
      padding: 0;
      background: transparent;
      color: var(--accent);
      font-family: "IBM Plex Mono", "IBM Plex Sans", monospace;
      font-size: 0.8rem;
      letter-spacing: 0.02em;
      user-select: text;
      cursor: text;
    }
    #stageWrap {
      display: flex;
      flex-direction: column;
      overflow: hidden;
      min-height: 0;
    }
    #stage {
      position: relative;
      flex: 1 1 auto;
      min-height: 0;
      width: 100%;
      border-radius: 12px;
      overflow: hidden;
      background:
        radial-gradient(ellipse 80% 60% at 50% 40%, rgba(61,214,198,0.06), transparent 70%),
        var(--bg-deep);
      touch-action: none;
      border: 1px solid rgba(120,160,200,0.1);
      box-shadow: inset 0 0 40px rgba(0,0,0,0.35);
    }
    #stage.is-tcp-drag,
    #stage.is-tcp-drag:active { cursor: move; }
    #stage canvas { display: block; width: 100% !important; height: 100% !important; }
    .tcp-drag-panel {
      position: absolute;
      right: 0.65rem;
      top: 0.65rem;
      z-index: 3;
      min-width: 11.5rem;
      max-width: min(16rem, calc(100% - 1.3rem));
      padding: 0.55rem 0.65rem 0.6rem;
      border: 1px solid rgba(240, 180, 41, 0.35);
      border-radius: 10px;
      background: rgba(11, 16, 24, 0.78);
      color: rgba(232, 240, 248, 0.92);
      backdrop-filter: blur(10px);
      -webkit-backdrop-filter: blur(10px);
      box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
      pointer-events: auto;
    }
    .tcp-drag-panel[hidden] { display: none !important; }
    .tcp-drag-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
      margin-bottom: 0.35rem;
    }
    .tcp-drag-head strong {
      font-size: 0.78rem;
      font-weight: 600;
      letter-spacing: 0.02em;
      color: #f0b429;
    }
    .tcp-drag-close {
      flex: 0 0 auto;
      width: 1.55rem;
      height: 1.55rem;
      margin: 0;
      padding: 0;
      border: 1px solid rgba(255, 255, 255, 0.18);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.06);
      color: rgba(232, 240, 248, 0.9);
      font-size: 1rem;
      line-height: 1;
      cursor: pointer;
    }
    .tcp-drag-close:hover { background: rgba(255, 255, 255, 0.12); }
    .tcp-drag-joints {
      margin: 0;
      padding: 0.35rem 0.4rem;
      border-radius: 6px;
      background: rgba(0, 0, 0, 0.28);
      font-family: "IBM Plex Mono", ui-monospace, monospace;
      font-size: 0.68rem;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-all;
      color: rgba(232, 240, 248, 0.95);
    }
    .tcp-drag-status {
      margin-top: 0.35rem;
      font-size: 0.68rem;
      line-height: 1.35;
      color: rgba(180, 198, 214, 0.88);
    }
    .tcp-drag-status.is-err { color: #ff8a9a; }
    .tcp-drag-status.is-ok { color: #7dcca0; }
    .tcp-trail-clear {
      --btn-h: 2rem;
      position: absolute;
      left: 0.65rem;
      top: 50%;
      transform: translateY(-50%);
      z-index: 2;
      display: inline-flex;
      align-items: center;
      justify-content: flex-start;
      gap: 0;
      box-sizing: border-box;
      height: 2rem;
      min-height: 2rem;
      min-width: 2rem;
      width: max-content;
      max-width: 2rem;
      margin: 0;
      padding: 0;
      overflow: hidden;
      white-space: nowrap;
      border: 1px solid rgba(255, 255, 255, 0.18);
      border-radius: 999px;
      background: rgba(11, 16, 24, 0.48);
      color: rgba(232, 240, 248, 0.88);
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      box-shadow: 0 4px 14px rgba(0, 0, 0, 0.28);
      cursor: pointer;
      pointer-events: auto;
      transition: max-width 0.22s ease, background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
    }
    .tcp-trail-clear-ico {
      flex: 0 0 auto;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 2rem;
      height: 2rem;
      font-size: 0.82rem;
      font-weight: 700;
      line-height: 1;
      transition: width 0.22s ease, opacity 0.15s ease;
    }
    .tcp-trail-clear-label {
      flex: 0 0 auto;
      display: inline-block;
      max-width: 0;
      opacity: 0;
      overflow: hidden;
      font-size: 0.72rem;
      font-weight: 550;
      line-height: 1;
      transition: max-width 0.22s ease, opacity 0.15s ease, padding 0.22s ease;
    }
    .tcp-trail-clear:hover:not(:disabled),
    .tcp-trail-clear:focus-visible:not(:disabled) {
      max-width: 10rem;
      background: rgba(11, 16, 24, 0.72);
      border-color: rgba(61, 214, 198, 0.45);
      color: #fff;
    }
    .tcp-trail-clear:hover:not(:disabled) .tcp-trail-clear-ico,
    .tcp-trail-clear:focus-visible:not(:disabled) .tcp-trail-clear-ico {
      width: 0; opacity: 0;
    }
    .tcp-trail-clear:hover:not(:disabled) .tcp-trail-clear-label,
    .tcp-trail-clear:focus-visible:not(:disabled) .tcp-trail-clear-label {
      max-width: 7rem;
      opacity: 1;
      padding-left: 0.7rem;
      padding-right: 0.7rem;
    }
    .tcp-trail-color {
      position: absolute;
      left: 0.65rem;
      top: calc(50% + 1.35rem);
      z-index: 2;
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      margin: 0;
      padding: 0.2rem 0.4rem 0.2rem 0.25rem;
      border: 1px solid rgba(255, 255, 255, 0.18);
      border-radius: 999px;
      background: rgba(11, 16, 24, 0.48);
      color: rgba(232, 240, 248, 0.88);
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      box-shadow: 0 4px 14px rgba(0, 0, 0, 0.28);
      cursor: pointer;
      pointer-events: auto;
      font-size: 0.68rem;
      line-height: 1;
      user-select: none;
    }
    .tcp-trail-color input[type="color"] {
      width: 1.35rem;
      height: 1.35rem;
      padding: 0;
      border: 1px solid rgba(255, 255, 255, 0.25);
      border-radius: 999px;
      background: transparent;
      cursor: pointer;
    }
    .tcp-trail-color-label { white-space: nowrap; opacity: 0.9; }
    .tcp-mass-control {
      position: absolute;
      left: 0.65rem;
      top: calc(50% + 2.85rem);
      z-index: 2;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      margin: 0;
      padding: 0.25rem 0.45rem 0.25rem 0.55rem;
      border: 1px solid rgba(240, 180, 41, 0.35);
      border-radius: 999px;
      background: rgba(11, 16, 24, 0.48);
      color: rgba(232, 240, 248, 0.88);
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      box-shadow: 0 4px 14px rgba(0, 0, 0, 0.28);
      pointer-events: auto;
      font-size: 0.68rem;
      line-height: 1;
      user-select: none;
    }
    .tcp-mass-control input[type="range"] {
      width: 5.5rem;
      margin: 0;
      accent-color: #f0b429;
      cursor: pointer;
    }
    .tcp-mass-label { color: #f0b429; font-weight: 600; letter-spacing: 0.02em; }
    .tcp-mass-val {
      min-width: 1.6rem;
      font-family: "IBM Plex Mono", monospace;
      font-variant-numeric: tabular-nums;
      color: rgba(232, 240, 248, 0.95);
    }
    .tcp-hold-resume {
      position: absolute;
      right: 0.65rem;
      top: 0.65rem;
      z-index: 3;
      margin: 0;
      padding: 0.35rem 0.7rem;
      border: 1px solid rgba(240, 180, 41, 0.4);
      border-radius: 999px;
      background: rgba(11, 16, 24, 0.78);
      color: #f0b429;
      font-size: 0.72rem;
      font-weight: 600;
      cursor: pointer;
      pointer-events: auto;
      backdrop-filter: blur(8px);
      box-shadow: 0 4px 14px rgba(0, 0, 0, 0.28);
    }
    .tcp-hold-resume[hidden] { display: none !important; }
    .tcp-hold-resume:hover {
      border-color: rgba(240, 180, 41, 0.7);
      background: rgba(240, 180, 41, 0.12);
    }
    .tcp-autosend {
      display: flex;
      align-items: center;
      gap: 0.4rem;
      margin: 0 0 0.4rem;
      font-size: 0.72rem;
      color: rgba(232, 240, 248, 0.9);
      cursor: pointer;
      user-select: none;
    }
    .tcp-autosend input {
      width: 0.95rem;
      height: 0.95rem;
      accent-color: #f0b429;
      cursor: pointer;
    }
    .hint {
      color: var(--muted); font-size: 0.76rem; line-height: 1.45;
      margin: 0.35rem 0 0.7rem; flex: 0 0 auto;
    }
    .row { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.4rem 0; align-items: center; }
    button, .btn {
      appearance: none;
      border: 1px solid rgba(120,160,200,0.22);
      border-radius: 10px;
      background: linear-gradient(180deg, rgba(61,214,198,0.16), rgba(61,214,198,0.06));
      color: var(--text);
      padding: 0.38rem 0.78rem;
      cursor: pointer;
      font: inherit;
      font-size: 0.8rem;
      font-weight: 500;
      letter-spacing: 0.01em;
      line-height: 1.25;
      box-shadow: var(--shadow-btn);
      transition:
        border-color 0.16s var(--ease),
        background 0.16s var(--ease),
        color 0.16s var(--ease),
        box-shadow 0.16s var(--ease),
        transform 0.12s var(--ease),
        opacity 0.16s var(--ease),
        filter 0.16s var(--ease);
    }
    button:hover:not(:disabled) {
      border-color: rgba(61,214,198,0.55);
      background: linear-gradient(180deg, rgba(61,214,198,0.26), rgba(61,214,198,0.1));
      box-shadow: 0 1px 0 rgba(255,255,255,0.08) inset, 0 4px 14px rgba(61,214,198,0.12);
      transform: translateY(-1px);
    }
    button:active:not(:disabled) {
      transform: translateY(0);
      filter: brightness(0.96);
      box-shadow: 0 1px 0 rgba(0,0,0,0.2) inset;
    }
    button:focus-visible {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(61,214,198,0.22);
    }
    button:disabled {
      opacity: 0.38;
      cursor: not-allowed;
      filter: grayscale(0.15);
      transform: none;
      box-shadow: none;
    }
    button.ok, button.primary {
      border-color: rgba(127,217,154,0.4);
      background: linear-gradient(180deg, rgba(127,217,154,0.28), rgba(61,214,198,0.12));
      color: #d8ffe6;
    }
    button.ok:hover:not(:disabled), button.primary:hover:not(:disabled) {
      border-color: rgba(127,217,154,0.7);
      background: linear-gradient(180deg, rgba(127,217,154,0.38), rgba(61,214,198,0.18));
      box-shadow: 0 1px 0 rgba(255,255,255,0.1) inset, 0 4px 16px rgba(127,217,154,0.18);
    }
    button.danger {
      border-color: rgba(240,113,120,0.38);
      background: linear-gradient(180deg, rgba(240,113,120,0.22), rgba(240,113,120,0.08));
      color: #ffc4c8;
    }
    button.danger:hover:not(:disabled) {
      border-color: rgba(240,113,120,0.65);
      background: linear-gradient(180deg, rgba(240,113,120,0.32), rgba(240,113,120,0.12));
      box-shadow: 0 1px 0 rgba(255,255,255,0.08) inset, 0 4px 16px rgba(240,113,120,0.16);
    }
    button.ghost {
      background: rgba(255,255,255,0.03);
      border-color: rgba(120,160,200,0.2);
      color: var(--muted);
    }
    button.ghost:hover:not(:disabled) {
      color: var(--text);
      border-color: rgba(61,214,198,0.4);
      background: rgba(61,214,198,0.08);
    }
    button.compact {
      padding: 0.28rem 0.55rem;
      font-size: 0.74rem;
      border-radius: 8px;
    }
    .jog-row button {
      min-width: 2.1rem;
      padding: 0.28rem 0.5rem;
      font-weight: 600;
      font-variant-numeric: tabular-nums;
    }
    .joint {
      display: grid; grid-template-columns: 2.2rem 1fr 3.6rem;
      gap: 0.45rem; align-items: center; margin: 0.32rem 0;
      font-variant-numeric: tabular-nums;
      font-family: "IBM Plex Mono", "IBM Plex Sans", monospace;
      font-size: 0.78rem;
    }
    .joint > span:first-child { color: var(--muted); font-weight: 500; }
    .bar {
      height: 7px; border-radius: 99px;
      background: rgba(255,255,255,0.05);
      overflow: hidden;
      box-shadow: inset 0 1px 2px rgba(0,0,0,0.35);
    }
    .bar > i {
      display: block; height: 100%; width: 0%;
      background: linear-gradient(90deg, var(--accent), #6ee7d8 45%, var(--spark));
      border-radius: 99px;
      box-shadow: 0 0 8px rgba(61,214,198,0.35);
      transition: width 0.12s linear;
    }
    .jog-row { display: flex; align-items: center; gap: 0.45rem; margin: 0.35rem 0; }
    .jog-row span { width: 2rem; color: var(--muted); font-size: 0.8rem; font-weight: 500; }
    label.hint { display: inline-flex; align-items: center; gap: 0.35rem; flex-wrap: wrap; }
    input[type=number], input[type=text], #absJoints {
      background: rgba(0, 0, 0, 0.28);
      border: 1px solid rgba(120,160,200,0.2);
      color: var(--text);
      border-radius: 8px;
      padding: 0.32rem 0.5rem;
      font: inherit;
      font-family: "IBM Plex Mono", "IBM Plex Sans", monospace;
      font-size: 0.78rem;
      transition: border-color 0.15s var(--ease), box-shadow 0.15s var(--ease), background 0.15s var(--ease);
    }
    input[type=number] { width: 5rem; }
    input[type=number]:hover, input[type=text]:hover, #absJoints:hover {
      border-color: rgba(61,214,198,0.35);
    }
    input[type=number]:focus, input[type=text]:focus, #absJoints:focus {
      outline: none;
      border-color: rgba(61,214,198,0.65);
      background: rgba(0, 0, 0, 0.38);
      box-shadow: 0 0 0 3px rgba(61,214,198,0.16);
    }
    #absLabel { display: block; cursor: pointer; }
    #absJoints { width: 100%; margin-top: 0.3rem; }
    #absProg {
      padding: 0.4rem 0.55rem;
      border-radius: 8px;
      background: rgba(61,214,198,0.06);
      border: 1px solid rgba(61,214,198,0.12);
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.72rem;
    }
    #toast {
      position: fixed; right: 1.1rem; bottom: 1.1rem; max-width: 360px;
      padding: 0.75rem 0.95rem; border-radius: 12px;
      border: 1px solid rgba(61,214,198,0.28);
      background: linear-gradient(165deg, rgba(32,46,66,0.95), var(--panel-solid));
      color: var(--text);
      display: none; z-index: 50;
      box-shadow: 0 12px 36px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.03) inset;
      backdrop-filter: blur(12px);
      font-size: 0.85rem;
      animation: toastIn 0.28s var(--ease);
    }
    @keyframes toastIn {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 0.01ms !important;
        transition-duration: 0.01ms !important;
      }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <div class="brand">sensors-arm</div>
      <div class="meta" id="siteLine">multi-arm · viz + control</div>
    </div>
    <div class="row">
      <span class="pill" id="dryPill">dry-run</span>
      <span class="pill" id="wsPill">ws …</span>
      <button type="button" class="danger compact" id="btnExit">安全退出</button>
    </div>
  </header>
  <main>
    <aside class="panel">
      <h2>Arms</h2>
      <p class="hint">切换型号仅换展示；需点「连接」才打开该臂读写（不会自动连所有臂）。</p>
      <div id="armList"></div>
      <div class="ip-row" title="来自 sensors YAML · robot_ip，只读（改 YAML 后重启）">
        <span class="k">IP</span>
        <input type="text" class="v" id="armIp" value="—" readonly tabindex="0" aria-readonly="true"/>
      </div>
      <div class="ip-row" title="工具 TCP 偏移（米，法兰坐标系）· YAML tcp_xyz，只读">
        <span class="k">TCP</span>
        <input type="text" class="v" id="armTcp" value="—" readonly tabindex="0" aria-readonly="true"/>
      </div>
      <div class="row conn-row">
        <button type="button" class="ok" id="btnConnect">连接</button>
        <button type="button" class="danger" id="btnDisconnect" disabled>断开</button>
      </div>
      <p class="hint" id="connHint">当前臂：未连接</p>
    </aside>
    <section class="panel" id="stageWrap">
      <h2 id="viewTitle">3D</h2>
      <div id="stage">
        <button type="button" class="tcp-trail-clear" id="tcpTrailClear" aria-label="清除轨迹" title="清除 TCP 轨迹点与连线（不影响琥珀球）">
          <span class="tcp-trail-clear-ico" aria-hidden="true">C</span>
          <span class="tcp-trail-clear-label">清除轨迹</span>
        </button>
        <label class="tcp-trail-color" title="仅影响之后新增的轨迹点与连线">
          <input type="color" id="tcpTrailColor" value="#3dd6c6" aria-label="轨迹颜色"/>
          <span class="tcp-trail-color-label">轨迹色</span>
        </label>
        <div class="tcp-mass-control" title="越大越钝（重质量阻尼）">
          <span class="tcp-mass-label">阻尼</span>
          <input type="range" id="tcpMass" min="5" max="200" step="1" value="28" aria-label="琥珀球质量/阻尼"/>
          <span class="tcp-mass-val" id="tcpMassVal">28</span>
        </div>
        <button type="button" class="tcp-hold-resume" id="tcpHoldResume" hidden title="放弃 IK 预览，琥珀球与 URDF 回到 live 读数">恢复跟随</button>
        <div class="tcp-drag-panel" id="tcpDragPanel" hidden>
          <div class="tcp-drag-head">
            <strong>拖拽 IK</strong>
            <button type="button" class="tcp-drag-close" id="tcpDragClose" aria-label="关闭并保持预览">×</button>
          </div>
          <label class="tcp-autosend" title="勾选后 IK 成功即走绝对下发（需已连接；可先 Arm）">
            <input type="checkbox" id="tcpAutoSend" checked/>
            <span>自动下发</span>
          </label>
          <pre class="tcp-drag-joints" id="tcpDragJoints">—</pre>
          <div class="tcp-drag-status" id="tcpDragStatus">拖拽琥珀球 → IK；勾选「自动下发」则写臂</div>
        </div>
      </div>
      <p class="hint" id="viewHint">加载模型… · 拖拽旋转 / 滚轮缩放 · 琥珀球拖拽测 IK · TCP 轨迹自动落点</p>
    </section>
    <aside class="panel">
      <h2>Read</h2>
      <div id="jointRead"></div>
      <p class="hint" id="poseLine">TCP —</p>
      <div class="row copy-row">
        <button type="button" class="ghost compact" id="btnCopyJoints">复制 joints</button>
        <button type="button" class="ghost compact" id="btnCopyPose">复制 pose</button>
        <button type="button" class="compact" id="btnFillAbs">填入下发</button>
        <span class="hint" id="copyHint"></span>
      </div>
      <h2 style="margin-top:1.15rem">Write</h2>
      <div class="row">
        <button type="button" class="ok" id="btnArm">Arm</button>
        <button type="button" class="danger" id="btnDisarm">Disarm</button>
        <button type="button" class="ghost" id="btnHomeGo">Home</button>
        <button type="button" class="ghost" id="btnHomeSet">设为 Home</button>
      </div>
      <label class="hint">点动 Δ° <input type="number" id="deltaDeg" value="2" step="0.5" min="0.1" max="15"/></label>
      <div id="jogBox"></div>
      <h2 style="margin-top:1rem">绝对下发</h2>
      <p class="hint" title="双击 joints 标签填入当前读角">T=clamp(d/v_norm, t_min, t_max) · 七段 jerk 插值（同 sensors-dcs）</p>
      <label class="hint" id="absLabel">joints
        <input type="text" id="absJoints" placeholder="0.00,0.00,0.00,0.00,0.00,0.00" autocomplete="off"/>
      </label>
      <div class="row" style="margin-top:0.4rem">
        <label class="hint">t_min <input type="number" id="absTMin" value="0.1" min="0.1" max="30" step="0.1" style="width:4rem"/></label>
        <label class="hint">t_max <input type="number" id="absTMax" value="30" min="0.1" max="30" step="0.1" style="width:4rem"/></label>
        <label class="hint">v_norm <input type="number" id="absVNorm" value="0.02" min="0.001" max="5" step="0.001" style="width:4.5rem"/></label>
      </div>
      <div class="row">
        <label class="hint">Tj <input type="number" id="absJerk" value="0.10" min="0.02" max="0.22" step="0.01" style="width:4rem"/></label>
        <label class="hint">Ta <input type="number" id="absAccel" value="0.15" min="0" max="0.30" step="0.01" style="width:4rem"/></label>
        <button type="button" class="ok primary" id="btnAbsSend">下发</button>
      </div>
      <p class="hint" id="absProg">绝对下发：空闲</p>
      <p class="hint" id="writeHint">写通道需配置 write_agent；未 Arm 前不下发。</p>
    </aside>
  </main>
  <div id="toast"></div>
<script>
(() => {
  const DEG = 180 / Math.PI;
  let arms = [];
  let activeId = null;
  let framesByAgent = {};
  let robot = null;
  let scene, camera, renderer, clock, controls;
  let loadToken = 0;
  let absRamp = { enabled: false, phase: 'idle', params: {} };
  let absTimingSeeded = false;
  let tcpMarker = null;
  let tcpDragActive = false;
  let tcpPreviewHold = false;
  let tcpPointerDown = false;
  let dragXyzrpy = null;
  let dragVelThree = null;
  let dragPreviewJoints = null;
  let dragHeldXyzrpy = null;
  let hasTcp = false;
  let lastTickMs = 0;
  let lastIkMs = 0;
  let ikInFlight = false;
  let ikPending = false;
  const TCP_MASS_MIN = 5;
  const TCP_MASS_MAX = 200;
  const TCP_MASS_DEFAULT = 28;
  const TCP_DAMP = 0.90;
  const TCP_V_MAX = 0.12;
  const TCP_IMPULSE_PX = 0.022;
  const IK_MIN_INTERVAL_MS = 80;
  const LS_TCP_MASS = 'sensors-arm.tcpMass';
  const LS_TCP_AUTO_SEND = 'sensors-arm.tcpAutoSend';
  let tcpMassCached = TCP_MASS_DEFAULT;
  let tcpAutoSendEnabled = true;
  let tcpAutoSendAfterIk = false;
  let tcpAutoSendInFlight = false;
  const TCP_PICK_MIN_PX = 22;
  const TCP_PICK_MAX_PX = 48;
  const TCP_MARKER_R = 0.016;
  const TCP_TIP_LINK_CANDIDATES = [
    'gripper_centor_link', 'gripper_center_link', 'flan', 'tool0', 'tcp',
    'ee_link', 'ft_kwr75_link', 'link6',
  ];
  const WAYPOINT_MAX = 400;
  const WAYPOINT_MIN_DIST = 0.0008;
  const TRAIL_COLOR_DEFAULT = 0x3dd6c6;
  const LS_TRAIL_COLOR = 'sensors-arm.poseTrailColor';
  let trailColor = TRAIL_COLOR_DEFAULT;
  const trailPosArr = [];
  let waypointGroup = null;
  let waypointGeom = null;
  let trailLine = null;
  let trailLineGeom = null;
  let trailLinePos = null;
  let trailLineCol = null;
  let _trailColTmp = null;

  function timingBody() {
    return {
      timing: 'scale_by_d',
      t_min_s: Number($('absTMin').value),
      t_max_s: Number($('absTMax').value),
      v_norm_rad_s: Number($('absVNorm').value),
      jerk_seg_frac: Number($('absJerk').value),
      accel_seg_frac: Number($('absAccel').value),
    };
  }

  function parseJointsInput() {
    const raw = ($('absJoints').value || '').trim();
    if (!raw) return { ok: false, error: 'joints 为空' };
    const parts = raw.split(/[\s,;]+/).filter(Boolean);
    if (parts.length < 6) return { ok: false, error: '需要 6 个关节角 (rad)' };
    const joints = [];
    for (let i = 0; i < 6; i++) {
      const v = Number(parts[i]);
      if (!Number.isFinite(v)) return { ok: false, error: 'joints_rad must be 6 floats' };
      joints.push(v);
    }
    return { ok: true, joints };
  }

  function fmtCsv6(arr) {
    if (!Array.isArray(arr) || arr.length < 6) return null;
    const vals = [];
    for (let i = 0; i < 6; i++) {
      const v = Number(arr[i]);
      if (!Number.isFinite(v)) return null;
      vals.push(v.toFixed(4));
    }
    return vals.join(',');
  }

  function flashCopy(msg) {
    const el = $('copyHint');
    if (!el) return;
    el.textContent = msg;
    clearTimeout(flashCopy._t);
    flashCopy._t = setTimeout(() => { if (el.textContent === msg) el.textContent = ''; }, 1800);
  }

  async function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }

  function currentJoints() {
    const arm = activeArm();
    if (!arm || !arm.connected) return null;
    const fr = framesByAgent[arm.read_agent];
    const j = fr && fr.payload && fr.payload.joints_rad;
    return Array.isArray(j) ? j : null;
  }

  function currentPose() {
    const arm = activeArm();
    if (!arm || !arm.connected) return null;
    const fr = framesByAgent[arm.read_agent];
    const p = fr && fr.payload && fr.payload.cartesian_xyzrpy;
    return Array.isArray(p) ? p : null;
  }

  function fillAbsFromRead() {
    const j = currentJoints();
    const csv = fmtCsv6(j);
    if (!csv) { toast('无当前读角（请先连接）'); return; }
    $('absJoints').value = csv;
    toast('已填入当前关节角');
  }

  function clampTcpMass(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return TCP_MASS_DEFAULT;
    return Math.max(TCP_MASS_MIN, Math.min(TCP_MASS_MAX, Math.round(n)));
  }
  function getTcpMass() { return tcpMassCached; }
  function setTcpMass(v) {
    tcpMassCached = clampTcpMass(v);
    const el = $('tcpMass');
    const val = $('tcpMassVal');
    if (el) el.value = String(tcpMassCached);
    if (val) val.textContent = String(tcpMassCached);
    try { localStorage.setItem(LS_TCP_MASS, String(tcpMassCached)); } catch (_) {}
    return tcpMassCached;
  }
  function isTcpAutoSendOn() {
    const el = $('tcpAutoSend');
    if (el) tcpAutoSendEnabled = !!el.checked;
    return tcpAutoSendEnabled;
  }
  function setTcpAutoSend(on) {
    tcpAutoSendEnabled = !!on;
    const el = $('tcpAutoSend');
    if (el) el.checked = tcpAutoSendEnabled;
    try { localStorage.setItem(LS_TCP_AUTO_SEND, tcpAutoSendEnabled ? '1' : '0'); } catch (_) {}
    return tcpAutoSendEnabled;
  }
  function fmtTcpXyz(arr) {
    if (!Array.isArray(arr) || arr.length < 3) return '—';
    return [0, 1, 2].map((i) => Number(arr[i]).toFixed(2)).join('; ');
  }
  function paintConn() {
    const arm = activeArm();
    const on = !!(arm && arm.connected);
    const btnC = $('btnConnect');
    const btnD = $('btnDisconnect');
    if (btnC) btnC.disabled = !arm || on;
    if (btnD) btnD.disabled = !arm || !on;
    const ipEl = $('armIp');
    if (ipEl) {
      const ep = arm && (arm.endpoint || arm.robot_ip);
      ipEl.value = ep || '—';
      ipEl.readOnly = true;
      ipEl.setAttribute('aria-readonly', 'true');
      ipEl.title = arm && arm.endpoint
        ? ('机械臂 IP（只读）· ' + arm.endpoint + ' · 改 sensors YAML robot_ip 后重启')
        : '未配置 robot_ip（只读）';
    }
    const tcpEl = $('armTcp');
    if (tcpEl) {
      tcpEl.value = arm ? fmtTcpXyz(arm.tcp_xyz) : '—';
      tcpEl.readOnly = true;
      tcpEl.setAttribute('aria-readonly', 'true');
      tcpEl.title = arm
        ? ('工具 TCP 偏移 xyz（m，只读）· ' + fmtTcpXyz(arm.tcp_xyz))
        : '未选臂';
    }
    const hint = $('connHint');
    if (hint) {
      hint.textContent = !arm
        ? '未选臂'
        : (on ? ('已连接 · ' + (arm.label || arm.id)) : ('未连接 · ' + (arm.label || arm.id) + ' — 点「连接」打开读写'));
    }
    ['btnArm', 'btnDisarm', 'btnHomeGo', 'btnHomeSet', 'btnAbsSend'].forEach((id) => {
      const el = $(id);
      if (el && id !== 'btnAbsSend') el.disabled = !on;
    });
  }

  function paintAbsProg() {
    const el = $('absProg');
    if (!el) return;
    const st = absRamp || {};
    if (st.enabled && st.phase === 'ramping') {
      el.textContent = '绝对下发：' + (st.message || ((st.ramp_index || 0) + '/' + (st.ramp_n || '?')));
      $('btnAbsSend').textContent = '取消';
    } else if (st.phase === 'completed') {
      el.textContent = '绝对下发：完成 — ' + (st.message || '');
      $('btnAbsSend').textContent = '下发';
    } else if (st.phase === 'error') {
      el.textContent = '绝对下发：失败 — ' + (st.last_error || st.message || '');
      $('btnAbsSend').textContent = '下发';
    } else {
      el.textContent = '绝对下发：' + (st.message || '空闲');
      $('btnAbsSend').textContent = '下发';
    }
  }

  const $ = (id) => document.getElementById(id);
  function toast(msg) {
    const el = $('toast');
    el.textContent = msg;
    el.style.display = 'block';
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.style.display = 'none'; }, 3200);
  }
  function activeArm() { return arms.find(a => a.id === activeId) || arms[0] || null; }

  function robotToThree(x, y, z) { return { x: x, y: z, z: -y }; }
  function threeToRobot(x, y, z) { return { x: x, y: -z, z: y }; }
  function parseXyz(arr) {
    if (!Array.isArray(arr) || arr.length < 3) return null;
    const x = Number(arr[0]), y = Number(arr[1]), z = Number(arr[2]);
    if (![x, y, z].every(Number.isFinite)) return null;
    return { x: x, y: y, z: z };
  }
  function parseTrailColorHex(raw) {
    const m = /^#?([0-9a-fA-F]{6})$/.exec(String(raw || '').trim());
    return m ? parseInt(m[1], 16) : null;
  }
  function trailColorToCss(n) {
    return '#' + ((Number(n) >>> 0) & 0xffffff).toString(16).padStart(6, '0');
  }
  function colorToRgb01(hexNum, out) {
    if (!_trailColTmp) _trailColTmp = new THREE.Color();
    _trailColTmp.setHex((hexNum >>> 0) & 0xffffff);
    out[0] = _trailColTmp.r;
    out[1] = _trailColTmp.g;
    out[2] = _trailColTmp.b;
  }
  function applyTrailColor(hexOrNum, opts) {
    opts = opts || {};
    let n = null;
    if (typeof hexOrNum === 'number' && Number.isFinite(hexOrNum)) n = hexOrNum >>> 0;
    else n = parseTrailColorHex(hexOrNum);
    if (n == null) n = TRAIL_COLOR_DEFAULT;
    trailColor = n & 0xffffff;
    const css = trailColorToCss(trailColor);
    const el = $('tcpTrailColor');
    if (el && el.value !== css) el.value = css;
    if (opts.persist !== false) {
      try { localStorage.setItem(LS_TRAIL_COLOR, css); } catch (_) {}
    }
    return css;
  }
  function rebuildTrailLine() {
    if (!trailLineGeom || !trailLinePos || !trailLineCol) return;
    const n = trailPosArr.length;
    const rgb = [0, 0, 0];
    for (let i = 0; i < n; i++) {
      const p = trailPosArr[i];
      trailLinePos[i * 3] = p.x;
      trailLinePos[i * 3 + 1] = p.y;
      trailLinePos[i * 3 + 2] = p.z;
      colorToRgb01(p.c != null ? p.c : TRAIL_COLOR_DEFAULT, rgb);
      trailLineCol[i * 3] = rgb[0];
      trailLineCol[i * 3 + 1] = rgb[1];
      trailLineCol[i * 3 + 2] = rgb[2];
    }
    trailLineGeom.getAttribute('position').needsUpdate = true;
    const colAttr = trailLineGeom.getAttribute('color');
    if (colAttr) colAttr.needsUpdate = true;
    trailLineGeom.setDrawRange(0, n);
    if (typeof trailLineGeom.computeBoundingSphere === 'function') trailLineGeom.computeBoundingSphere();
  }
  function clearTrail() {
    trailPosArr.length = 0;
    if (waypointGroup) {
      while (waypointGroup.children.length) {
        const ch = waypointGroup.children[0];
        waypointGroup.remove(ch);
        if (ch.material && typeof ch.material.dispose === 'function') {
          try { ch.material.dispose(); } catch (_) {}
        }
      }
    }
    rebuildTrailLine();
  }
  function pushTrailWaypoint(x, y, z) {
    if (!waypointGroup || !waypointGeom) return false;
    const last = trailPosArr.length ? trailPosArr[trailPosArr.length - 1] : null;
    if (last) {
      const dx = x - last.x, dy = y - last.y, dz = z - last.z;
      if ((dx * dx + dy * dy + dz * dz) < (WAYPOINT_MIN_DIST * WAYPOINT_MIN_DIST)) return false;
    }
    if (trailPosArr.length >= WAYPOINT_MAX) {
      trailPosArr.shift();
      const oldest = waypointGroup.children[0];
      if (oldest) {
        waypointGroup.remove(oldest);
        if (oldest.material && typeof oldest.material.dispose === 'function') {
          try { oldest.material.dispose(); } catch (_) {}
        }
      }
    }
    const c = trailColor & 0xffffff;
    trailPosArr.push({ x: x, y: y, z: z, c: c });
    const bead = new THREE.Mesh(waypointGeom, new THREE.MeshBasicMaterial({ color: c }));
    bead.position.set(x, y, z);
    bead.raycast = function() {};
    waypointGroup.add(bead);
    rebuildTrailLine();
    return true;
  }
  function pushTrailFromRobotXyz(x, y, z) {
    const p = robotToThree(x, y, z);
    return pushTrailWaypoint(p.x, p.y, p.z);
  }
  function pushTrailFromTcpMarker() {
    if (!tcpMarker || !tcpMarker.visible) return false;
    return pushTrailWaypoint(tcpMarker.position.x, tcpMarker.position.y, tcpMarker.position.z);
  }

  function setDragStatus(kind, text) {
    const el = $('tcpDragStatus');
    if (!el) return;
    el.classList.remove('is-ok', 'is-err');
    if (kind === 'ok') el.classList.add('is-ok');
    if (kind === 'err') el.classList.add('is-err');
    el.textContent = text;
  }
  function renderDragJoints(joints) {
    const el = $('tcpDragJoints');
    if (!el) return;
    if (!Array.isArray(joints) || joints.length < 6) { el.textContent = '—'; return; }
    const lines = [];
    for (let i = 0; i < 6; i++) lines.push('J' + (i + 1) + '  ' + Number(joints[i]).toFixed(4));
    el.textContent = lines.join('\n');
  }
  function openTcpDragPanel() {
    const panel = $('tcpDragPanel');
    if (panel) panel.hidden = false;
    const host = $('stage');
    if (host) host.classList.add('is-tcp-drag');
    setHoldResumeVisible(false);
    setDragStatus('', '拖拽琥珀球 → IK；勾选「自动下发」则写臂');
  }
  function setHoldResumeVisible(on) {
    const btn = $('tcpHoldResume');
    if (btn) btn.hidden = !on;
  }
  function resumeLiveTcpFollow() {
    tcpPreviewHold = false;
    dragPreviewJoints = null;
    dragHeldXyzrpy = null;
    dragXyzrpy = null;
    tcpDragActive = false;
    tcpPointerDown = false;
    if (dragVelThree) dragVelThree.set(0, 0, 0);
    ikPending = false;
    if (controls) controls.enabled = true;
    const panel = $('tcpDragPanel');
    if (panel) panel.hidden = true;
    const host = $('stage');
    if (host) host.classList.remove('is-tcp-drag');
    setHoldResumeVisible(false);
    tcpAutoSendAfterIk = false;
    tcpAutoSendInFlight = false;
    renderDragJoints(null);
    setDragStatus('', '拖拽琥珀球 → IK；勾选「自动下发」则写臂');
    paintJoints();
    syncTcpMarkerFromLive();
  }
  function closeTcpDragPreview() {
    // Keep last IK / ball pose for inspection — do not snap back to live FK.
    tcpDragActive = false;
    tcpPointerDown = false;
    tcpAutoSendAfterIk = false;
    if (Array.isArray(dragXyzrpy) && dragXyzrpy.length >= 6) {
      dragHeldXyzrpy = dragXyzrpy.slice(0, 6);
    }
    if (Array.isArray(dragPreviewJoints) && dragPreviewJoints.length >= 6) {
      tcpPreviewHold = true;
    } else if (dragHeldXyzrpy) {
      tcpPreviewHold = true;
    }
    dragXyzrpy = null;
    if (dragVelThree) dragVelThree.set(0, 0, 0);
    ikPending = false;
    if (controls) controls.enabled = true;
    const panel = $('tcpDragPanel');
    if (panel) panel.hidden = true;
    const host = $('stage');
    if (host) host.classList.remove('is-tcp-drag');
    setHoldResumeVisible(!!tcpPreviewHold);
    if (tcpPreviewHold && Array.isArray(dragPreviewJoints)) {
      paintJointsFromArray(dragPreviewJoints);
      if (dragHeldXyzrpy) setTcpPose(dragHeldXyzrpy, { skipTrail: true, force: true });
    }
  }
  function queueTcpIkSend() {
    if (!tcpDragActive || !isTcpAutoSendOn()) return;
    tcpAutoSendAfterIk = true;
    if (!tcpAutoSendInFlight) autoSendTcpIkJoints();
  }
  async function autoSendTcpIkJoints() {
    if (tcpAutoSendInFlight || !tcpAutoSendAfterIk || !tcpDragActive) return;
    if (!isTcpAutoSendOn()) { tcpAutoSendAfterIk = false; return; }
    if (!Array.isArray(dragPreviewJoints) || dragPreviewJoints.length < 6) return;
    const arm = activeArm();
    if (!arm) return;
    if (!arm.connected) {
      setDragStatus('err', '自动下发：请先连接该臂');
      tcpAutoSendAfterIk = false;
      return;
    }
    if (!arm.write_agent) {
      setDragStatus('err', '自动下发：无 write_agent');
      tcpAutoSendAfterIk = false;
      return;
    }
    tcpAutoSendInFlight = true;
    tcpAutoSendAfterIk = false;
    setDragStatus('', '直接下发中…');
    try {
      // Drag path: timing=direct — no abs-ramp / seven-segment interpolation.
      const body = {
        arm_id: arm.id,
        joints_rad: dragPreviewJoints.slice(0, 6),
        timing: 'direct',
      };
      const r = await fetch('/api/arm/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then((x) => x.json());
      if (!tcpDragActive) return;
      if (r && r.ok) {
        setDragStatus('ok', '已直发（无插值）');
      } else {
        setDragStatus('err', '下发失败: ' + ((r && r.error) ? String(r.error) : 'unknown'));
      }
    } catch (e) {
      if (tcpDragActive) setDragStatus('err', '下发失败: ' + String(e && e.message || e));
    } finally {
      tcpAutoSendInFlight = false;
      if (tcpAutoSendAfterIk && tcpDragActive) autoSendTcpIkJoints();
    }
  }
  function findUrdfTcpObject() {
    if (!robot) return null;
    if (robot.links) {
      for (let i = 0; i < TCP_TIP_LINK_CANDIDATES.length; i++) {
        const n = TCP_TIP_LINK_CANDIDATES[i];
        if (robot.links[n]) return robot.links[n];
      }
    }
    let best = null;
    let bestDepth = -1;
    robot.traverse((obj) => {
      if (!obj || !obj.isObject3D) return;
      const name = String(obj.name || '');
      if (!name) return;
      const depth = (obj.parent ? 1 : 0) + (obj.children ? obj.children.length : 0);
      if (/gripper_centor|gripper_center|flan|tool0|^tcp$|ee_link|ft_kwr75|link6/i.test(name)) {
        const score = /gripper_centor|gripper_center|flan|tool0/i.test(name) ? 100 : 10;
        if (score + depth > bestDepth) { bestDepth = score + depth; best = obj; }
      }
    });
    return best;
  }
  function setTcpPose(xyzrpy, opts) {
    opts = opts || {};
    if (!tcpMarker) return false;
    if (!opts.force && (tcpDragActive || tcpPreviewHold)) return false;
    const xyz = parseXyz(xyzrpy);
    if (!xyz) return false;
    const p = robotToThree(xyz.x, xyz.y, xyz.z);
    tcpMarker.position.set(p.x, p.y, p.z);
    const rx = Number(xyzrpy[3]), ry = Number(xyzrpy[4]), rz = Number(xyzrpy[5]);
    if ([rx, ry, rz].every(Number.isFinite)) tcpMarker.rotation.set(rx, rz, -ry, 'XYZ');
    tcpMarker.visible = true;
    hasTcp = true;
    if (!opts.skipTrail) pushTrailWaypoint(p.x, p.y, p.z);
    return true;
  }
  function syncTcpMarkerFromUrdf() {
    if (tcpDragActive || tcpPreviewHold || !tcpMarker || !robot) return false;
    const tip = findUrdfTcpObject();
    if (!tip) return false;
    tip.updateMatrixWorld(true);
    const w = new THREE.Vector3();
    tip.getWorldPosition(w);
    // Tip link (gripper_centor / flan) is already the visual TCP — do NOT add
    // yaml tcp_xyz again (that double-offset was pushing Cell B's ball ~18cm past jaws).
    tcpMarker.position.copy(w);
    tip.getWorldQuaternion(tcpMarker.quaternion);
    tcpMarker.visible = true;
    hasTcp = true;
    pushTrailWaypoint(w.x, w.y, w.z);
    return true;
  }
  function syncTcpMarkerFromLive() {
    if (tcpDragActive || tcpPreviewHold) return;
    // Prefer URDF tip so the amber ball stays on the gripper mesh. FK cartesian
    // (flange + tcp_xyz) can sit past a short EOAT model or diverge with provisional DH.
    if (syncTcpMarkerFromUrdf()) return;
    const pose = currentPose();
    if (pose) setTcpPose(pose);
    else if (tcpMarker) { tcpMarker.visible = false; hasTcp = false; }
  }
  function tcpPointerOver(ev) {
    if (!tcpMarker || !tcpMarker.visible || !renderer) return false;
    const canvas = renderer.domElement;
    const rect = canvas.getBoundingClientRect();
    tcpMarker.updateMatrixWorld(true);
    const worldPos = new THREE.Vector3();
    tcpMarker.getWorldPosition(worldPos);
    const center = worldPos.clone().project(camera);
    // Three NDC z in [-1,1]; reject only clearly behind the camera.
    if (center.z < -1 || center.z > 1) return false;
    const sx = (center.x * 0.5 + 0.5) * rect.width;
    const sy = (-center.y * 0.5 + 0.5) * rect.height;
    const mx = ev.clientX - rect.left;
    const my = ev.clientY - rect.top;
    const edge = worldPos.clone().add(new THREE.Vector3(TCP_MARKER_R, 0, 0)).project(camera);
    const pickR = Math.max(TCP_PICK_MIN_PX, Math.min(TCP_PICK_MAX_PX, Math.hypot(
      (edge.x - center.x) * 0.5 * rect.width,
      (edge.y - center.y) * 0.5 * rect.height,
    ) * 2.8));
    return ((mx - sx) * (mx - sx) + (my - sy) * (my - sy)) <= pickR * pickR;
  }
  function poseFromMarkerWorld() {
    if (!tcpMarker) return null;
    const rob = threeToRobot(tcpMarker.position.x, tcpMarker.position.y, tcpMarker.position.z);
    return [rob.x, rob.y, rob.z, 0, 0, 0];
  }
  function beginTcpDrag() {
    // Leaving a held preview: continue from held ball / joints.
    tcpPreviewHold = false;
    // Seed from FK TCP (full xyzrpy) so the first IK is reachable. Mixing URDF-tip
    // xyz with FK rpy was a common source of residual~3e-2 failures.
    let src = currentPose();
    if (Array.isArray(dragHeldXyzrpy) && dragHeldXyzrpy.length >= 6) {
      src = dragHeldXyzrpy;
    } else if (!parseXyz(src)) {
      if (!hasTcp || !tcpMarker || !tcpMarker.visible) {
        syncTcpMarkerFromUrdf();
      }
      src = poseFromMarkerWorld();
    }
    const xyz = parseXyz(src);
    if (!xyz) { toast('无 TCP（请先连接或等 URDF 加载）'); return false; }
    const rx = Number(src[3]), ry = Number(src[4]), rz = Number(src[5]);
    dragXyzrpy = [
      xyz.x, xyz.y, xyz.z,
      Number.isFinite(rx) ? rx : 0,
      Number.isFinite(ry) ? ry : 0,
      Number.isFinite(rz) ? rz : 0,
    ];
    if (dragVelThree) dragVelThree.set(0, 0, 0);
    openTcpDragPanel();
    // Snap ball to the IK seed pose (FK frame) so drag deltas stay consistent.
    const p0 = robotToThree(dragXyzrpy[0], dragXyzrpy[1], dragXyzrpy[2]);
    tcpMarker.position.set(p0.x, p0.y, p0.z);
    tcpMarker.visible = true;
    hasTcp = true;
    tcpDragActive = true;
    dragPreviewJoints = currentJoints() || dragPreviewJoints;
    scheduleIk(true);
    return true;
  }
  async function runIkOnce() {
    if (!tcpDragActive || !dragXyzrpy) return;
    if (ikInFlight) { ikPending = true; return; }
    const arm = activeArm();
    if (!arm) return;
    ikInFlight = true;
    ikPending = false;
    lastIkMs = performance.now();
    if (!tcpPointerDown) setDragStatus('', '求解 IK…');
    try {
      const seed = dragPreviewJoints || currentJoints();
      const body = { arm_id: arm.id, xyzrpy: dragXyzrpy.slice(0, 6) };
      if (Array.isArray(seed) && seed.length >= 6) body.seed_joints_rad = seed.slice(0, 6).map(Number);
      const r = await fetch('/api/arm/ik', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then((x) => x.json());
      if (!tcpDragActive) return;
      if (r && r.ok && Array.isArray(r.joints_rad) && r.joints_rad.length >= 6) {
        dragPreviewJoints = r.joints_rad.slice(0, 6).map(Number);
        renderDragJoints(dragPreviewJoints);
        const csv = fmtCsv6(dragPreviewJoints);
        if (csv) $('absJoints').value = csv;
        paintJointsFromArray(dragPreviewJoints);
        // Refresh rpy from achieved FK so the next xyz-only drag step stays reachable
        // (freezing start rpy forever makes CS66 IK fail after a few cm).
        const achieved = r.cartesian && r.cartesian.cartesian_xyzrpy;
        if (Array.isArray(achieved) && achieved.length >= 6) {
          dragXyzrpy[3] = Number(achieved[3]) || dragXyzrpy[3];
          dragXyzrpy[4] = Number(achieved[4]) || dragXyzrpy[4];
          dragXyzrpy[5] = Number(achieved[5]) || dragXyzrpy[5];
        }
        const posErr = (r.pos_err_m != null) ? (' · |Δp|=' + Number(r.pos_err_m).toFixed(4) + 'm') : '';
        const auto = isTcpAutoSendOn();
        setDragStatus('ok', 'IK ok' + posErr + (auto ? ' · 准备下发' : ' · 仅预览'));
        if (auto) queueTcpIkSend();
      } else {
        tcpAutoSendAfterIk = false;
        setDragStatus('err', 'IK 失败: ' + ((r && r.error) ? String(r.error) : 'unknown'));
      }
    } catch (e) {
      if (tcpDragActive) setDragStatus('err', 'IK 失败: ' + String(e && e.message || e));
    } finally {
      ikInFlight = false;
      if (ikPending && tcpDragActive) { ikPending = false; scheduleIk(true); }
    }
  }
  function scheduleIk(force) {
    if (!tcpDragActive || !dragXyzrpy) return;
    const now = performance.now();
    if (!force && (now - lastIkMs) < IK_MIN_INTERVAL_MS) { ikPending = true; return; }
    runIkOnce();
  }
  function tickTcpDrag(dt) {
    if (!tcpDragActive || !dragXyzrpy || !tcpMarker || !dragVelThree) return;
    if (dragVelThree.lengthSq() > 1e-12) {
      tcpMarker.position.x += dragVelThree.x * dt;
      tcpMarker.position.y += dragVelThree.y * dt;
      tcpMarker.position.z += dragVelThree.z * dt;
      dragVelThree.multiplyScalar(Math.pow(TCP_DAMP, dt * 60));
      if (dragVelThree.lengthSq() < 1e-10) dragVelThree.set(0, 0, 0);
      const rob = threeToRobot(tcpMarker.position.x, tcpMarker.position.y, tcpMarker.position.z);
      dragXyzrpy[0] = rob.x;
      dragXyzrpy[1] = rob.y;
      dragXyzrpy[2] = rob.z;
      pushTrailFromTcpMarker();
      scheduleIk(false);
    } else if (ikPending) {
      scheduleIk(true);
    }
  }

  function initThree() {
    const host = $('stage');
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x070c14);
    camera = new THREE.PerspectiveCamera(40, 1, 0.01, 50);
    camera.position.set(1.2, 0.9, 1.2);
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    host.appendChild(renderer.domElement);
    if (typeof THREE.OrbitControls === 'function') {
      controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.target.set(0, 0.35, 0);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.minDistance = 0.25;
      controls.maxDistance = 8;
      controls.update();
    } else {
      camera.lookAt(0, 0.35, 0);
      console.warn('[sensors-arm] OrbitControls missing');
    }
    const amb = new THREE.AmbientLight(0xffffff, 0.55);
    const dir = new THREE.DirectionalLight(0xffffff, 0.85);
    dir.position.set(2, 3, 1);
    scene.add(amb, dir);
    const grid = new THREE.GridHelper(2, 20, 0x3dd6c6, 0x1a2740);
    grid.position.y = 0;
    scene.add(grid);
    tcpMarker = new THREE.Mesh(
      new THREE.SphereGeometry(TCP_MARKER_R, 16, 16),
      new THREE.MeshBasicMaterial({ color: 0xf0b429, depthTest: true }),
    );
    const tipAxes = new THREE.AxesHelper(0.05);
    tipAxes.raycast = function() {};
    tcpMarker.add(tipAxes);
    // Invisible larger hit proxy — screen pick uses radius, this helps Raycaster fallback.
    const hitProxy = new THREE.Mesh(
      new THREE.SphereGeometry(TCP_MARKER_R * 2.2, 8, 8),
      new THREE.MeshBasicMaterial({ visible: false }),
    );
    hitProxy.name = 'tcpHitProxy';
    tcpMarker.add(hitProxy);
    tcpMarker.raycast = function() {};
    tcpMarker.visible = false;
    scene.add(tcpMarker);
    dragVelThree = new THREE.Vector3();
    _trailColTmp = new THREE.Color();
    waypointGeom = new THREE.SphereGeometry(0.0035, 10, 10);
    waypointGroup = new THREE.Group();
    scene.add(waypointGroup);
    trailLinePos = new Float32Array(WAYPOINT_MAX * 3);
    trailLineCol = new Float32Array(WAYPOINT_MAX * 3);
    trailLineGeom = new THREE.BufferGeometry();
    trailLineGeom.setAttribute('position', new THREE.BufferAttribute(trailLinePos, 3));
    trailLineGeom.setAttribute('color', new THREE.BufferAttribute(trailLineCol, 3));
    trailLineGeom.setDrawRange(0, 0);
    trailLine = new THREE.Line(trailLineGeom, new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.85,
    }));
    scene.add(trailLine);
    try {
      const saved = localStorage.getItem(LS_TRAIL_COLOR);
      const parsed = parseTrailColorHex(saved);
      if (parsed != null) trailColor = parsed;
    } catch (_) {}
    applyTrailColor(trailColor, { persist: false });
    const trailClearBtn = $('tcpTrailClear');
    if (trailClearBtn) {
      trailClearBtn.addEventListener('click', (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        clearTrail();
      });
    }
    const trailColorEl = $('tcpTrailColor');
    if (trailColorEl) {
      trailColorEl.addEventListener('input', () => applyTrailColor(trailColorEl.value));
      trailColorEl.addEventListener('change', () => applyTrailColor(trailColorEl.value));
    }
    const canvas = renderer.domElement;
    const right = new THREE.Vector3();
    const up = new THREE.Vector3();
    let tcpDragPointerId = null;
    function applyTcpImpulse(dx, dy) {
      if (!dragVelThree) return;
      const dist = controls ? Math.max(0.15, camera.position.distanceTo(controls.target)) : 1.2;
      const scale = dist * TCP_IMPULSE_PX;
      right.setFromMatrixColumn(camera.matrix, 0);
      up.setFromMatrixColumn(camera.matrix, 1);
      const mass = Math.max(TCP_MASS_MIN, getTcpMass());
      dragVelThree.addScaledVector(right, (dx * scale) / mass);
      dragVelThree.addScaledVector(up, (-dy * scale) / mass);
      const speed = dragVelThree.length();
      if (speed > TCP_V_MAX) dragVelThree.multiplyScalar(TCP_V_MAX / speed);
    }
    function onTcpDocMove(ev) {
      if (!tcpPointerDown || !tcpDragActive || !dragXyzrpy) return;
      if (tcpDragPointerId != null && ev.pointerId !== tcpDragPointerId) return;
      const dx = ev.clientX - (canvas._tcpLastPx || ev.clientX);
      const dy = ev.clientY - (canvas._tcpLastPy || ev.clientY);
      canvas._tcpLastPx = ev.clientX;
      canvas._tcpLastPy = ev.clientY;
      applyTcpImpulse(dx, dy);
      ev.preventDefault();
    }
    function endTcpPointer(ev) {
      if (!tcpPointerDown) return;
      if (tcpDragPointerId != null && ev && ev.pointerId != null && ev.pointerId !== tcpDragPointerId) return;
      tcpPointerDown = false;
      tcpDragPointerId = null;
      document.removeEventListener('pointermove', onTcpDocMove, true);
      document.removeEventListener('pointerup', endTcpPointer, true);
      document.removeEventListener('pointercancel', endTcpPointer, true);
      if (controls) controls.enabled = true;
      try { if (ev) canvas.releasePointerCapture(ev.pointerId); } catch (_) {}
      if (tcpDragActive) scheduleIk(true);
    }
    canvas.addEventListener('pointerdown', (ev) => {
      if (ev.button !== 0) return;
      if (!tcpPointerOver(ev)) return;
      if (!beginTcpDrag()) return;
      tcpPointerDown = true;
      tcpDragPointerId = ev.pointerId;
      if (controls) controls.enabled = false;
      try { canvas.setPointerCapture(ev.pointerId); } catch (_) {}
      canvas._tcpLastPx = ev.clientX;
      canvas._tcpLastPy = ev.clientY;
      document.addEventListener('pointermove', onTcpDocMove, true);
      document.addEventListener('pointerup', endTcpPointer, true);
      document.addEventListener('pointercancel', endTcpPointer, true);
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }, true);
    const closeBtn = $('tcpDragClose');
    if (closeBtn) closeBtn.addEventListener('click', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      closeTcpDragPreview();
    });
    const resumeBtn = $('tcpHoldResume');
    if (resumeBtn) resumeBtn.addEventListener('click', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      resumeLiveTcpFollow();
    });
    try {
      const savedMass = localStorage.getItem(LS_TCP_MASS);
      if (savedMass != null && savedMass !== '') setTcpMass(savedMass);
      else setTcpMass(TCP_MASS_DEFAULT);
    } catch (_) { setTcpMass(TCP_MASS_DEFAULT); }
    const massEl = $('tcpMass');
    if (massEl) {
      massEl.addEventListener('input', () => setTcpMass(massEl.value));
      massEl.addEventListener('change', () => setTcpMass(massEl.value));
    }
    try {
      const savedAuto = localStorage.getItem(LS_TCP_AUTO_SEND);
      if (savedAuto === '0' || savedAuto === 'false') setTcpAutoSend(false);
      else setTcpAutoSend(true);
    } catch (_) { setTcpAutoSend(true); }
    const autoEl = $('tcpAutoSend');
    if (autoEl) {
      autoEl.addEventListener('change', () => setTcpAutoSend(autoEl.checked));
    }
    clock = new THREE.Clock();
    lastTickMs = performance.now();
    function resize() {
      const w = Math.max(1, host.clientWidth);
      const h = Math.max(1, host.clientHeight);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
    }
    resize();
    window.addEventListener('resize', resize);
    if (typeof ResizeObserver === 'function') {
      new ResizeObserver(resize).observe(host);
    }
    (function loop() {
      requestAnimationFrame(loop);
      const now = performance.now();
      let dt = (now - lastTickMs) / 1000;
      lastTickMs = now;
      if (!(dt > 0) || dt > 0.1) dt = 1 / 60;
      tickTcpDrag(dt);
      if (!tcpDragActive && !tcpPreviewHold) syncTcpMarkerFromLive();
      if (controls && controls.enableDamping) controls.update();
      renderer.render(scene, camera);
    })();
  }

  function clearRobot() {
    if (tcpDragActive || tcpPreviewHold) resumeLiveTcpFollow();
    if (robot) { scene.remove(robot); robot = null; }
  }

  function softMaterials(root) {
    root.traverse((c) => {
      if (!c.isMesh || !c.material) return;
      const mats = Array.isArray(c.material) ? c.material : [c.material];
      mats.forEach((m) => {
        if (!m) return;
        if (m.side != null) m.side = THREE.DoubleSide;
      });
    });
  }

  function resolveJointNames(arm) {
    const catalog = Array.isArray(arm.joint_names) ? arm.joint_names.filter(Boolean) : [];
    if (catalog.length) return catalog;
    if (!robot || !robot.joints) return [];
    return Object.keys(robot.joints).filter((n) => {
      const j = robot.joints[n];
      const t = (j && (j.jointType || j.type) || '').toLowerCase();
      return t === 'revolute' || t === 'continuous' || t === 'prismatic';
    });
  }

  function loadModel(arm) {
    const token = ++loadToken;
    clearRobot();
    $('viewTitle').textContent = (arm.brand || '') + ' · ' + (arm.product || arm.model);
    if (!arm.urdf) {
      $('viewHint').textContent = '该型号无 URDF（stub）— 仅关节条显示。可在 models_catalog.yaml 绑定网格。';
      return;
    }
    if (typeof URDFLoader === 'undefined') {
      $('viewHint').textContent = 'URDFLoader 未加载';
      return;
    }
    const urdfUrl = String(arm.urdf);
    const pathOnly = urdfUrl.split('?')[0];
    $('viewHint').textContent = '加载 ' + pathOnly + ' …';
    const manager = new THREE.LoadingManager();
    const loader = new URDFLoader(manager);
    loader.workingPath = pathOnly.replace(/[^/]+$/, '');
    loader.load(urdfUrl, (r) => {
      if (token !== loadToken) return;
      softMaterials(r);
      r.rotation.x = -Math.PI / 2; // Z-up → Y-up
      if (arm.mirror_y) r.scale.y = -1;
      robot = r;
      scene.add(robot);
      const keys = robot.joints ? Object.keys(robot.joints) : [];
      $('viewHint').textContent = (arm.label || arm.id) + ' · ' + arm.model
        + ' · joints[' + keys.join(',') + ']'
        + ' · 拖拽旋转 / 琥珀球 IK · TCP 轨迹自动落点';
      paintJoints();
      // Prefer FK pose; fall back to URDF tip (needed when CS66 FK unsupported).
      syncTcpMarkerFromLive();
    }, undefined, (err) => {
      if (token !== loadToken) return;
      $('viewHint').textContent = 'URDF 失败: ' + (err && err.message ? err.message : err);
    });
  }

  function paintJointsFromArray(j) {
    const arm = activeArm();
    if (!arm || !robot || !robot.joints || !Array.isArray(j)) return 0;
    const names = resolveJointNames(arm);
    const offs = arm.joint_offset_rad || [];
    const signs = arm.joint_signs || [];
    let applied = 0;
    for (let i = 0; i < Math.min(6, j.length, names.length); i++) {
      const joint = robot.joints[names[i]];
      if (!joint || typeof joint.setJointValue !== 'function') continue;
      // SolidWorks export sometimes ships limit lower=upper=0; widen for viz.
      if (joint.limit && Number(joint.limit.lower) === 0 && Number(joint.limit.upper) === 0) {
        joint.limit.lower = -Math.PI * 2;
        joint.limit.upper = Math.PI * 2;
      }
      const q = (signs[i] == null ? 1 : Number(signs[i])) * (Number(j[i]) - Number(offs[i] || 0));
      joint.setJointValue(q);
      applied += 1;
    }
    robot.updateMatrixWorld(true);
    return applied;
  }

  function paintJoints() {
    if ((tcpDragActive || tcpPreviewHold) && Array.isArray(dragPreviewJoints)) {
      paintJointsFromArray(dragPreviewJoints);
      return;
    }
    if (tcpPreviewHold) return;
    const arm = activeArm();
    if (!arm || !robot || !robot.joints) return;
    const fr = framesByAgent[arm.read_agent];
    const j = fr && fr.payload && fr.payload.joints_rad;
    if (!Array.isArray(j)) return;
    const names = resolveJointNames(arm);
    const applied = paintJointsFromArray(j);
    if (applied === 0 && names.length) {
      $('viewHint').textContent = '关节未匹配: want=' + names.join(',')
        + ' have=' + Object.keys(robot.joints).join(',');
    }
    // After joints update, refresh TCP ball (FK or URDF tip).
    if (!tcpDragActive && !tcpPreviewHold) syncTcpMarkerFromLive();
  }

  function renderArmList() {
    const box = $('armList');
    box.innerHTML = '';
    arms.forEach((a) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'arm-tab' + (a.id === activeId ? ' active' : '');
      const on = !!a.connected;
      const ip = a.robot_ip || (a.endpoint ? String(a.endpoint).split(':')[0] : '');
      b.innerHTML = '<strong><span class="conn-dot' + (on ? ' on' : '') + '"></span>'
        + (a.label || a.id) + '</strong>'
        + '<span class="sub">' + (a.brand || '') + ' ' + (a.product || a.model)
        + (ip ? ' · ' + ip : '')
        + (a.write_agent ? ' · R/W' : ' · RO')
        + (on ? ' · 已连接' : ' · 未连接') + '</span>';
      b.onclick = () => {
        if (tcpDragActive || tcpPreviewHold) resumeLiveTcpFollow();
        if (a.id !== activeId) clearTrail();
        activeId = a.id;
        renderArmList();
        loadModel(a);
        renderControls();
        paintConn();
        paintRead();
      };
      box.appendChild(b);
    });
    paintConn();
  }

  function renderControls() {
    const arm = activeArm();
    const box = $('jogBox');
    box.innerHTML = '';
    if (!arm) return;
    const n = arm.num_joints || 6;
    for (let i = 0; i < n; i++) {
      const row = document.createElement('div');
      row.className = 'jog-row';
      row.innerHTML = '<span>J' + (i + 1) + '</span>'
        + '<button type="button" data-j="' + i + '" data-s="-1">−</button>'
        + '<button type="button" data-j="' + i + '" data-s="1">+</button>';
      box.appendChild(row);
    }
    box.querySelectorAll('button').forEach((b) => {
      b.onclick = async () => {
        if (!arm.write_agent) { toast('无 write_agent'); return; }
        const delta = Number($('deltaDeg').value || 2);
        const body = { arm_id: arm.id, jog_joint: Number(b.dataset.j), delta_deg: delta * Number(b.dataset.s) };
        const r = await fetch('/api/arm/command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(x => x.json());
        if (!r.ok) toast(r.error || 'jog failed');
      };
    });
    $('writeHint').textContent = arm.write_agent
      ? ('write_agent=' + arm.write_agent + ' · maxΔ 受驱动 soft limit 约束')
      : '只读臂 — 未配置 write_agent';
  }

  function paintRead() {
    const arm = activeArm();
    const box = $('jointRead');
    if (!arm) { box.innerHTML = ''; return; }
    if (!arm.connected) {
      box.innerHTML = '<p class="hint">未连接 — 关节读数不可用</p>';
      $('poseLine').textContent = 'TCP —';
      return;
    }
    const fr = framesByAgent[arm.read_agent];
    const j = fr && fr.payload && fr.payload.joints_rad;
    const n = arm.num_joints || 6;
    let html = '';
    for (let i = 0; i < n; i++) {
      const rad = Array.isArray(j) ? Number(j[i] || 0) : 0;
      const deg = rad * DEG;
      const pct = Math.max(0, Math.min(100, 50 + (deg / 180) * 50));
      html += '<div class="joint"><span>J' + (i + 1) + '</span><div class="bar"><i style="width:' + pct + '%"></i></div><span>' + deg.toFixed(1) + '°</span></div>';
    }
    box.innerHTML = html;
    const cart = fr && fr.payload && fr.payload.cartesian_xyzrpy;
    $('poseLine').textContent = Array.isArray(cart)
      ? ('TCP xyzrpy: ' + cart.map(x => Number(x).toFixed(3)).join(', '))
      : 'TCP —';
    paintJoints();
  }

  async function boot() {
    initThree();
    const st = await fetch('/api/status').then(r => r.json());
    arms = st.arms || [];
    activeId = arms[0] && arms[0].id;
    $('siteLine').textContent = (st.config && st.config.site) || 'arm-lab';
    $('dryPill').textContent = st.sensors_dry_run ? 'dry-run' : 'LIVE';
    $('dryPill').className = 'pill' + (st.sensors_dry_run ? '' : ' warn');
    renderArmList();
    if (arms[0]) loadModel(arms[0]);
    renderControls();
    paintConn();

    $('btnConnect').onclick = async () => {
      const a = activeArm(); if (!a) return;
      const r = await fetch('/api/arm/connect', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ arm_id: a.id }),
      }).then((x) => x.json());
      if (r.ok) {
        a.connected = true;
        renderArmList();
        toast(r.message || '已连接');
      } else {
        toast(r.error || '连接失败');
      }
    };
    $('btnDisconnect').onclick = async () => {
      const a = activeArm(); if (!a) return;
      const r = await fetch('/api/arm/disconnect', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ arm_id: a.id }),
      }).then((x) => x.json());
      if (r.ok) {
        a.connected = false;
        delete framesByAgent[a.read_agent];
        if (a.write_agent) delete framesByAgent[a.write_agent];
        renderArmList();
        paintRead();
        toast(r.message || '已断开');
      } else {
        toast(r.error || '断开失败');
      }
    };
    $('btnCopyJoints').onclick = async () => {
      try {
        const csv = fmtCsv6(currentJoints());
        if (!csv) throw new Error('无当前 joints（请先连接）');
        await copyText(csv);
        flashCopy('已复制 joints');
      } catch (e) {
        flashCopy(String(e && e.message || e));
      }
    };
    $('btnCopyPose').onclick = async () => {
      try {
        const csv = fmtCsv6(currentPose());
        if (!csv) throw new Error('无当前 pose（请先连接）');
        await copyText(csv);
        flashCopy('已复制 pose');
      } catch (e) {
        flashCopy(String(e && e.message || e));
      }
    };
    $('btnFillAbs').onclick = () => fillAbsFromRead();

    $('btnArm').onclick = async () => {
      const a = activeArm(); if (!a) return;
      if (!a.connected) { toast('请先连接该臂'); return; }
      const r = await fetch('/api/arm/command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ arm_id: a.id, arm: true }) }).then(x => x.json());
      toast(r.ok ? 'armed' : (r.error || 'arm failed'));
    };
    $('btnDisarm').onclick = async () => {
      const a = activeArm(); if (!a) return;
      const r = await fetch('/api/arm/command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ arm_id: a.id, disarm: true }) }).then(x => x.json());
      toast(r.ok ? 'disarmed' : (r.error || 'disarm failed'));
    };
    if (st.arm_abs_ramp && st.arm_abs_ramp.params && !absTimingSeeded) {
      const p = st.arm_abs_ramp.params;
      if (p.t_min_s != null) $('absTMin').value = p.t_min_s;
      if (p.t_max_s != null) $('absTMax').value = p.t_max_s;
      if (p.v_norm_rad_s != null) $('absVNorm').value = p.v_norm_rad_s;
      if (p.jerk_seg_frac != null) $('absJerk').value = p.jerk_seg_frac;
      if (p.accel_seg_frac != null) $('absAccel').value = p.accel_seg_frac;
      absTimingSeeded = true;
      absRamp = st.arm_abs_ramp;
      paintAbsProg();
    }

    $('btnHomeGo').onclick = async () => {
      const a = activeArm(); if (!a) return;
      const body = { arm_id: a.id, ...timingBody() };
      const r = await fetch('/api/arm/home/go', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(x => x.json());
      toast(r.ok ? (r.message || 'Home 斜坡已开始') : (r.error || 'home failed'));
    };
    $('btnHomeSet').onclick = async () => {
      const a = activeArm(); if (!a) return;
      const r = await fetch('/api/arm/home/set', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ arm_id: a.id }) }).then(x => x.json());
      toast(r.ok ? 'home set' : (r.error || 'set failed'));
    };
    $('absLabel').ondblclick = (e) => { e.preventDefault(); fillAbsFromRead(); };
    $('btnAbsSend').onclick = async () => {
      const a = activeArm(); if (!a) return;
      if (absRamp && absRamp.enabled) {
        const r = await fetch('/api/arm/command', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ arm_id: a.id, cancel_abs_ramp: true }),
        }).then((x) => x.json());
        toast(r.ok ? '已取消' : (r.error || 'cancel failed'));
        return;
      }
      if (!a.connected) { toast('请先连接该臂'); return; }
      const parsed = parseJointsInput();
      if (!parsed.ok) { toast(parsed.error); return; }
      const body = { arm_id: a.id, joints_rad: parsed.joints, ...timingBody() };
      const r = await fetch('/api/arm/command', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then((x) => x.json());
      toast(r.ok ? (r.message || '斜坡已开始') : (r.error || 'abs send failed'));
    };
    $('btnExit').onclick = async () => {
      await fetch('/api/shutdown', { method: 'POST' });
      toast('正在退出…');
    };

    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    let ws;
    function connect() {
      ws = new WebSocket(proto + '://' + location.host + '/ws');
      ws.onopen = () => { $('wsPill').textContent = 'ws ok'; };
      ws.onclose = () => { $('wsPill').textContent = 'ws …'; setTimeout(connect, 800); };
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          (msg.frames || []).forEach((f) => { framesByAgent[f.agent_id] = f; });
          if (Array.isArray(msg.arms) && msg.arms.length) {
            const prev = activeId;
            const connChanged = msg.arms.some((na) => {
              const oa = arms.find((x) => x.id === na.id);
              return !oa || !!oa.connected !== !!na.connected;
            });
            arms = msg.arms;
            if (!arms.find((x) => x.id === activeId) && arms[0]) activeId = arms[0].id;
            if (connChanged || prev !== activeId) renderArmList();
            else paintConn();
          }
          if (msg.arm_abs_ramp) {
            absRamp = msg.arm_abs_ramp;
            if (msg.arm_abs_ramp.params && !absTimingSeeded) {
              const p = msg.arm_abs_ramp.params;
              if (p.t_min_s != null) $('absTMin').value = p.t_min_s;
              if (p.t_max_s != null) $('absTMax').value = p.t_max_s;
              if (p.v_norm_rad_s != null) $('absVNorm').value = p.v_norm_rad_s;
              if (p.jerk_seg_frac != null) $('absJerk').value = p.jerk_seg_frac;
              if (p.accel_seg_frac != null) $('absAccel').value = p.accel_seg_frac;
              absTimingSeeded = true;
            }
            paintAbsProg();
          }
          paintRead();
        } catch (e) {}
      };
    }
    connect();
  }
  boot();
})();
</script>
</body>
</html>
"""


class ArmSessionBody(BaseModel):
    arm_id: str


class ArmCommandBody(BaseModel):
    arm_id: str
    arm: bool = False
    disarm: bool = False
    stop: bool = False
    joints_rad: list[float] | None = None
    jog_joint: int | None = None
    delta_deg: float | None = None
    delta_rad: float | None = None
    cancel_abs_ramp: bool = False
    timing: str | None = None
    duration_s: float | None = None
    t_min_s: float | None = None
    t_max_s: float | None = None
    v_norm_rad_s: float | None = None
    jerk_seg_frac: float | None = None
    accel_seg_frac: float | None = None


class ArmHomeBody(BaseModel):
    arm_id: str
    joints_rad: list[float] | None = None
    t_min_s: float | None = None
    t_max_s: float | None = None
    v_norm_rad_s: float | None = None
    jerk_seg_frac: float | None = None
    accel_seg_frac: float | None = None


class ArmIkBody(BaseModel):
    arm_id: str
    xyzrpy: list[float] = Field(min_length=6, max_length=6)
    seed_joints_rad: list[float] | None = None


def create_app(orch: Orchestrator) -> FastAPI:
    app = FastAPI(title="sensors-arm", docs_url="/api/docs")
    assets = static_dir()
    if assets.is_dir():
        # ec616 meshes may be a symlink into sensors-dcs
        app.mount(
            "/assets",
            StaticFiles(directory=str(assets), follow_symlink=True),
            name="assets",
        )

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(PAGE)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "app": "sensors-arm"}

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        return orch.status()

    @app.get("/api/arms")
    async def arms() -> dict[str, Any]:
        return {"arms": orch.arms_descriptor()}

    @app.post("/api/arm/connect")
    async def arm_connect(body: ArmSessionBody) -> dict[str, Any]:
        return orch.arm_connect(body.arm_id)

    @app.post("/api/arm/disconnect")
    async def arm_disconnect(body: ArmSessionBody) -> dict[str, Any]:
        return orch.arm_disconnect(body.arm_id)

    @app.post("/api/arm/command")
    async def arm_cmd(body: ArmCommandBody) -> dict[str, Any]:
        return orch.arm_command(
            body.arm_id,
            arm=body.arm,
            disarm=body.disarm,
            stop=body.stop,
            joints_rad=body.joints_rad,
            jog_joint=body.jog_joint,
            delta_deg=body.delta_deg,
            delta_rad=body.delta_rad,
            cancel_abs_ramp=body.cancel_abs_ramp,
            timing=body.timing,
            duration_s=body.duration_s,
            t_min_s=body.t_min_s,
            t_max_s=body.t_max_s,
            v_norm_rad_s=body.v_norm_rad_s,
            jerk_seg_frac=body.jerk_seg_frac,
            accel_seg_frac=body.accel_seg_frac,
        )

    @app.get("/api/arm/home")
    async def arm_home(arm_id: str) -> dict[str, Any]:
        return orch.arm_home_get(arm_id)

    @app.post("/api/arm/home/set")
    async def arm_home_set(body: ArmHomeBody) -> dict[str, Any]:
        return orch.arm_home_set(body.arm_id, body.joints_rad)

    @app.post("/api/arm/home/go")
    async def arm_home_go(body: ArmHomeBody) -> dict[str, Any]:
        return orch.arm_home_go(
            body.arm_id,
            t_min_s=body.t_min_s,
            t_max_s=body.t_max_s,
            v_norm_rad_s=body.v_norm_rad_s,
            jerk_seg_frac=body.jerk_seg_frac,
            accel_seg_frac=body.accel_seg_frac,
        )

    @app.get("/api/arm/abs-ramp")
    async def arm_abs_ramp_get() -> dict[str, Any]:
        return orch._abs_ramp.status()

    @app.post("/api/arm/ik")
    async def arm_ik(body: ArmIkBody) -> dict[str, Any]:
        return orch.arm_ik(body.arm_id, body.xyzrpy, seed=body.seed_joints_rad)

    @app.post("/api/shutdown")
    async def shutdown() -> dict[str, Any]:
        return orch.request_shutdown()

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        last_seq = -1
        try:
            while True:
                snap = orch.hub.snapshot()
                if snap is not None:
                    seq = int(snap.get("_hub_seq") or 0)
                    if seq != last_seq:
                        last_seq = seq
                        await ws.send_json(snap)
                await asyncio.sleep(1.0 / max(5.0, float(orch.cfg.runtime.viz_hz)))
        except WebSocketDisconnect:
            return
        except Exception:  # noqa: BLE001
            return

    @app.exception_handler(KeyError)
    async def _key(request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)

    return app
