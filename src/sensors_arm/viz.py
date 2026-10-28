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
    .remote-block { margin: 0.85rem 0 0.35rem; }
    .remote-block .ip-row .v {
      color: var(--text, #e8eef7);
      outline: none;
    }
    .remote-block .ip-row .v:focus {
      color: var(--accent);
    }
    .remote-hint-ok { color: var(--ok) !important; }
    .remote-hint-err { color: var(--danger, #f07178) !important; }
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
    button.state-on {
      box-shadow: 0 0 0 2px rgba(127,217,154,0.55), 0 0 18px rgba(127,217,154,0.22);
      filter: none;
      opacity: 1;
    }
    button.ok.state-on, button#btnArm.state-on {
      border-color: rgba(127,217,154,0.85);
      background: linear-gradient(180deg, rgba(127,217,154,0.45), rgba(61,214,198,0.2));
      color: #eafff2;
    }
    button.danger.state-on, button#btnDisarm.state-on {
      border-color: rgba(240,113,120,0.8);
      background: linear-gradient(180deg, rgba(240,113,120,0.4), rgba(240,113,120,0.16));
      color: #ffe0e3;
      box-shadow: 0 0 0 2px rgba(240,113,120,0.45), 0 0 18px rgba(240,113,120,0.18);
    }
    #remoteDiffLog {
      margin: 0.25rem 0 0.5rem;
      padding: 0.45rem 0.55rem;
      border-radius: 8px;
      border: 1px solid rgba(240,113,120,0.28);
      background: rgba(0,0,0,0.28);
      color: #ffc4c8;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.68rem;
      line-height: 1.4;
      white-space: pre-wrap;
      word-break: break-all;
      max-height: 9rem;
      overflow: auto;
      display: none;
    }
    #remoteDiffLog.show { display: block; }
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
    .ip-row.max-delta-row .v { flex: 1; min-width: 0; }
    .ip-row.max-delta-row button {
      flex: 0 0 auto; padding: 0.28rem 0.55rem; font-size: 0.72rem;
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
      <div class="ip-row max-delta-row" title="本 Cell 写驱动单次关节 |Δq| 上限（max_delta_deg），与其它臂独立">
        <span class="k">最大Δ°</span>
        <input type="number" class="v" id="armMaxDelta" min="0.1" max="180" step="0.5" value="15" aria-label="本臂最大角度偏差"/>
        <button type="button" class="ghost compact" id="btnMaxDeltaApply">应用</button>
      </div>
      <div class="row conn-row">
        <button type="button" class="ok" id="btnConnect">连接</button>
        <button type="button" class="danger" id="btnDisconnect" disabled>断开</button>
      </div>
      <p class="hint" id="connHint">当前臂：未连接</p>
      <div class="remote-block">
        <h2>远程关节</h2>
        <p class="hint">拉取 Gello 等源的 6 轴 JSON（字段 joints，rad），驱动本 Cell 三维画布；连接成功后自动 Disarm 一次。</p>
        <div class="ip-row" title="远程 joints 地址，如 http://127.0.0.1:7020/joints">
          <span class="k">URL</span>
          <input type="text" class="v" id="remoteUrl" placeholder="http://127.0.0.1:7020/joints" autocomplete="off" spellcheck="false"/>
        </div>
        <div class="row conn-row">
          <button type="button" class="ok" id="btnRemoteConnect">拉取</button>
          <button type="button" class="danger" id="btnRemoteDisconnect" disabled>停止</button>
          <button type="button" class="ghost" id="btnRemotePrecheck" disabled title="采样 5s 确认静止后与硬件关节比 &lt;2°">预下发</button>
          <button type="button" class="ok" id="btnRemoteSend" disabled title="预检通过后：实时远程 joints → CS dense writeServoj（servoj_once，无嵌套斜坡/无每点 idle）；再点停止">远程连续下发</button>
        </div>
        <p class="hint" id="remoteHint">未拉取远程</p>
        <pre id="remoteDiffLog" aria-live="polite"></pre>
      </div>
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
        <div class="tcp-mass-control" title="平移与旋转共用：越大越钝（重质量阻尼）">
          <span class="tcp-mass-label">阻尼</span>
          <input type="range" id="tcpMass" min="5" max="200" step="1" value="28" aria-label="TCP 平移/旋转质量阻尼"/>
          <span class="tcp-mass-val" id="tcpMassVal">28</span>
        </div>
        <button type="button" class="tcp-hold-resume" id="tcpHoldResume" hidden title="（已改为拖拽结束后自动恢复跟随）">恢复跟随</button>
        <div class="tcp-drag-panel" id="tcpDragPanel" hidden>
          <div class="tcp-drag-head">
            <strong>拖拽 IK</strong>
            <button type="button" class="tcp-drag-close" id="tcpDragClose" aria-label="关闭并恢复 live 跟随">×</button>
          </div>
          <label class="tcp-autosend" title="勾选后 IK 成功即走绝对下发（需已连接；可先 Arm）">
            <input type="checkbox" id="tcpAutoSend" checked/>
            <span>自动下发</span>
          </label>
          <pre class="tcp-drag-joints" id="tcpDragJoints">—</pre>
          <div class="tcp-drag-status" id="tcpDragStatus">拖拽琥珀球 → IK；勾选「自动下发」则写臂</div>
        </div>
      </div>
      <p class="hint" id="viewHint">加载模型… · 拖拽旋转 / 滚轮缩放 · 琥珀=TCP · 蓝球=法兰 · TCP 轨迹自动落点</p>
    </section>
    <aside class="panel">
      <h2>Read</h2>
      <div id="jointRead"></div>
      <p class="hint" id="jointsLine">joints —</p>
      <p class="hint" id="poseLine">TCP —</p>
      <p class="hint" id="flangeLine">法兰 —</p>
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
      <label class="hint">点动 Δ° <input type="number" id="deltaDeg" value="2" step="0.5" min="0.1" max="180" title="单次点动角度；上限随左侧「最大Δ°」变化"/></label>
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
  /** Per-cell remote joints stream: { url, on, joints, step, es, pollTimer, abort }. */
  const remoteByArm = {};
  const LS_REMOTE_URL = 'sensors-arm.remoteUrl.';
  let robot = null;
  let scene, camera, renderer, clock, controls;
  let loadToken = 0;
  let absRamp = { enabled: false, phase: 'idle', params: {} };
  let absTimingSeeded = false;
  let tcpMarker = null;
  let flangeMarker = null;
  let tcpRotGizmo = null;
  let tcpRotRings = [];
  let tcpDragActive = false;
  let tcpPreviewHold = false;
  let tcpPointerDown = false;
  let tcpDragMode = 'translate'; // 'translate' | 'rotate'
  let tcpRotAxis = 0; // 0:X 1:Y 2:Z in TCP local frame
  let tcpRotLastAngle = 0;
  let tcpRotOriOk = true; // last rotate IK matched target orientation
  let dragXyzrpy = null;
  let dragVelThree = null;
  let dragRotVel = 0; // rad/s about active local tcpRotAxis (damped, like translate)
  let dragPreviewJoints = null;
  let dragHeldXyzrpy = null;
  let hasTcp = false;
  let _tcpRaycaster = null;
  let _tcpNdc = null;
  let _tcpHitPlane = null;
  let _tcpHitPt = null;
  let _tcpTmpV = null;
  let _tcpTmpV2 = null;
  let _tcpTmpV3 = null;
  let _tcpTmpQ = null;
  let _tcpTmpQ2 = null;
  let _tcpTmpE = null;
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
  const TCP_OMEGA_MAX = 6.0; // rad/s — rotate coast cap
  const TCP_ROT_IMPULSE = 55.0; // pointer Δangle → residual ω / mass (coast after release)
  const TCP_ROT_DAMP = 0.94; // lighter than translate damp — coast stays visible
  const TCP_ROT_DIRECT = 0.85; // fraction of pointer Δangle applied immediately while dragging
  // Server interactive IK is LM (~ms); ~25 Hz is enough for amber-ball preview.
  const IK_MIN_INTERVAL_MS = 40;
  const LS_TCP_MASS = 'sensors-arm.tcpMass';
  const LS_TCP_AUTO_SEND = 'sensors-arm.tcpAutoSend';
  let tcpMassCached = TCP_MASS_DEFAULT;
  let tcpAutoSendEnabled = true;
  let tcpAutoSendAfterIk = false;
  let tcpAutoSendInFlight = false;
  const TCP_PICK_MIN_PX = 22;
  const TCP_PICK_MAX_PX = 48;
  const TCP_MARKER_R = 0.016;
  const FLANGE_MARKER_R = 0.014;
  const TCP_ROT_RING_R = 0.22; // was 0.116 — larger CAD-style rings
  const TCP_ROT_TUBE = 0.0065;
  const TCP_ROT_HIT_TUBE = 0.028;
  const TCP_ROT_COLORS = [0xe74c3c, 0x2ecc71, 0x3498db]; // X Y Z — CAD-like
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

  const REMOTE_PRECHECK_S = 5;
  const REMOTE_STABLE_MAX_DEG = 0.5;
  const REMOTE_SEND_MAX_DELTA_DEG = 2;

  function remoteState(armId) {
    if (!armId) return null;
    if (!remoteByArm[armId]) {
      remoteByArm[armId] = {
        url: '',
        on: false,
        joints: null,
        step: 0,
        es: null,
        pollTimer: null,
        mode: '',
        sendReady: false,
        queuedJoints: null,
        prechecking: false,
        precheckToken: 0,
        /** Continuous direct write of live remote joints (no abs-ramp). */
        remoteStreaming: false,
        streamWriteInFlight: false,
        streamWritePending: null,
        lastStreamedStep: null,
      };
    }
    return remoteByArm[armId];
  }

  function isArmed(arm) {
    if (!arm || !arm.write_agent) return false;
    const fr = framesByAgent[arm.write_agent];
    return !!(fr && fr.payload && fr.payload.armed);
  }

  function hardwareJoints(arm) {
    if (!arm || !arm.connected) return null;
    const fr = framesByAgent[arm.read_agent];
    const j = fr && fr.payload && fr.payload.joints_rad;
    if (!Array.isArray(j) || j.length < 6) return null;
    const out = [];
    for (let i = 0; i < 6; i++) {
      const v = Number(j[i]);
      if (!Number.isFinite(v)) return null;
      out.push(v);
    }
    return out;
  }

  function stopRemoteStreaming(armId) {
    const st = remoteState(armId);
    if (!st) return;
    st.remoteStreaming = false;
    st.streamWritePending = null;
    st.streamWriteInFlight = false;
  }

  function clearRemoteSendGate(armId, reason) {
    const st = remoteState(armId);
    if (!st) return;
    st.sendReady = false;
    st.queuedJoints = null;
    st.prechecking = false;
    st.precheckToken = (st.precheckToken || 0) + 1;
    stopRemoteStreaming(armId);
    if (armId === activeId) {
      paintRemoteButtons();
      paintRemoteHint();
      if (reason) {
        const el = $('remoteHint');
        if (el && st.on) {
          el.textContent = (el.textContent || '') + ' · ' + reason;
        }
      }
    }
  }

  function showRemoteDiffLog(text) {
    const el = $('remoteDiffLog');
    if (!el) return;
    if (!text) {
      el.textContent = '';
      el.classList.remove('show');
      return;
    }
    el.textContent = text;
    el.classList.add('show');
  }

  function paintArmButtons() {
    const arm = activeArm();
    const on = !!(arm && arm.connected);
    const armed = isArmed(arm);
    const btnA = $('btnArm');
    const btnD = $('btnDisarm');
    if (btnA) {
      btnA.disabled = !on;
      btnA.classList.toggle('state-on', on && armed);
      btnA.textContent = (on && armed) ? 'Armed' : 'Arm';
      btnA.title = (on && armed) ? '已使能' : '使能写通道';
    }
    if (btnD) {
      btnD.disabled = !on;
      btnD.classList.toggle('state-on', on && !armed);
      btnD.textContent = (on && !armed) ? 'Disarmed' : 'Disarm';
      btnD.title = (on && !armed) ? '已下使能' : '下使能并停止';
    }
    ['btnHomeGo', 'btnHomeSet'].forEach((id) => {
      const el = $(id);
      if (el) el.disabled = !on;
    });
  }

  function paintRemoteButtons() {
    const arm = activeArm();
    const btnPre = $('btnRemotePrecheck');
    const btnSend = $('btnRemoteSend');
    const btnC = $('btnRemoteConnect');
    const btnD = $('btnRemoteDisconnect');
    const urlEl = $('remoteUrl');
    if (!arm) {
      if (btnPre) btnPre.disabled = true;
      if (btnSend) btnSend.disabled = true;
      if (btnC) btnC.disabled = true;
      if (btnD) btnD.disabled = true;
      if (urlEl) urlEl.disabled = true;
      return;
    }
    const st = remoteState(arm.id);
    const armed = isArmed(arm);
    const connected = !!arm.connected;
    if (urlEl && document.activeElement !== urlEl) {
      urlEl.value = st.url || '';
      urlEl.disabled = !!st.on;
    }
    if (btnC) btnC.disabled = !!st.on;
    if (btnD) btnD.disabled = !st.on;
    // 预下发: 远程拉取中 + 臂已连接 + Armed + 未在预检/连续下发
    if (btnPre) {
      btnPre.disabled = !(st.on && connected && armed && !st.prechecking && !st.remoteStreaming);
      btnPre.textContent = st.prechecking ? '预检中…' : '预下发';
    }
    // 远程连续下发: 预检通过后可启动；运行中再点即停止
    if (btnSend) {
      if (st.remoteStreaming) {
        btnSend.disabled = false;
        btnSend.textContent = '停止连续下发';
        btnSend.classList.remove('ok');
        btnSend.classList.add('danger');
      } else {
        btnSend.disabled = !(st.on && connected && armed && st.sendReady && !st.prechecking);
        btnSend.textContent = '远程连续下发';
        btnSend.classList.add('ok');
        btnSend.classList.remove('danger');
      }
    }
  }

  function extractRemoteJoints(obj) {
    if (!obj || typeof obj !== 'object') return null;
    const arr = obj.joints != null ? obj.joints : obj.pose;
    if (!Array.isArray(arr) || arr.length < 6) return null;
    const out = [];
    for (let i = 0; i < 6; i++) {
      const v = Number(arr[i]);
      if (!Number.isFinite(v)) return null;
      out.push(v);
    }
    return out;
  }

  function applyRemoteFrame(armId, obj) {
    const st = remoteState(armId);
    if (!st || !st.on) return;
    const j = extractRemoteJoints(obj);
    if (!j) return;
    st.joints = j;
    st.step = Number(obj.step) || 0;
    if (st.remoteStreaming) {
      enqueueRemoteStreamWrite(armId, j, st.step);
    }
    if (armId === activeId) {
      paintRemoteHint();
      paintJoints();
      paintReadRemoteOverlay();
    }
  }

  function paintRemoteHint() {
    const arm = activeArm();
    const el = $('remoteHint');
    if (!el) return;
    if (!arm) {
      el.textContent = '未选臂';
      el.className = 'hint';
      paintRemoteButtons();
      return;
    }
    const st = remoteState(arm.id);
    if (st.prechecking) {
      el.textContent = '预下发采样中（' + REMOTE_PRECHECK_S + 's 静止检测）…';
      el.className = 'hint';
    } else if (st.remoteStreaming) {
      const step = st.step != null ? st.step : '—';
      el.textContent = '远程连续下发中 · CS servoj_once · step=' + step + '（再点按钮停止）';
      el.className = 'hint remote-hint-ok';
    } else if (st.on) {
      const step = st.step != null ? st.step : '—';
      let msg = '远程拉取中 · step=' + step + (st.mode ? (' · ' + st.mode) : '');
      if (st.sendReady) msg += ' · 预检通过，可远程连续下发';
      el.textContent = msg;
      el.className = 'hint remote-hint-ok';
    } else {
      el.textContent = '未拉取远程';
      el.className = 'hint';
    }
    paintRemoteButtons();
  }

  function jointDiffRows(remoteJ, hwJ) {
    const rows = [];
    for (let i = 0; i < 6; i++) {
      const dRad = Number(remoteJ[i]) - Number(hwJ[i]);
      const dDeg = dRad * DEG;
      rows.push({ i: i + 1, dDeg: dDeg, abs: Math.abs(dDeg), remote: Number(remoteJ[i]), hw: Number(hwJ[i]) });
    }
    rows.sort((a, b) => b.abs - a.abs);
    return rows;
  }

  function formatRemoteDiffFail(remoteJ, rows) {
    const rj = remoteJ.map((x) => Number(x).toFixed(6)).join(', ');
    let lines = ['remote joints (rad): [' + rj + ']', 'Δdeg (desc):'];
    rows.forEach((r) => {
      lines.push(
        '  J' + r.i + '  Δ=' + (r.dDeg >= 0 ? '+' : '') + r.dDeg.toFixed(3)
          + '°  remote=' + r.remote.toFixed(4) + '  hw=' + r.hw.toFixed(4)
      );
    });
    return lines.join('\n');
  }

  async function remotePrecheckActive() {
    const arm = activeArm();
    if (!arm) return;
    const st = remoteState(arm.id);
    if (!st.on) { toast('请先拉取远程'); return; }
    if (!arm.connected) { toast('请先连接机械臂'); return; }
    if (!isArmed(arm)) { toast('请先 Arm 使能'); return; }
    if (st.prechecking || st.remoteStreaming) return;

    st.sendReady = false;
    st.queuedJoints = null;
    st.prechecking = true;
    const token = (st.precheckToken || 0) + 1;
    st.precheckToken = token;
    showRemoteDiffLog('');
    paintRemoteHint();

    const samples = [];
    const t0 = performance.now();
    const deadline = t0 + REMOTE_PRECHECK_S * 1000;
    while (performance.now() < deadline) {
      if (st.precheckToken !== token) return; // aborted (disarm / stop)
      if (!st.on) {
        st.prechecking = false;
        toast('远程已停止，预检取消');
        paintRemoteHint();
        return;
      }
      if (!arm.connected || !isArmed(arm)) {
        st.prechecking = false;
        toast('连接/Arm 状态变化，预检取消');
        paintRemoteHint();
        return;
      }
      if (Array.isArray(st.joints) && st.joints.length >= 6) {
        samples.push(st.joints.slice(0, 6));
      }
      const left = Math.max(0, deadline - performance.now());
      const el = $('remoteHint');
      if (el) {
        el.textContent = '预下发采样中… ' + (left / 1000).toFixed(1) + 's · n=' + samples.length;
        el.className = 'hint';
      }
      paintRemoteButtons();
      await new Promise((r) => setTimeout(r, 50));
    }
    if (st.precheckToken !== token) return;
    st.prechecking = false;

    if (samples.length < 10) {
      toast('预检失败：远程样本过少');
      paintRemoteHint();
      return;
    }
    // Peak-to-peak per joint over the window → source must be still.
    const mins = samples[0].slice();
    const maxs = samples[0].slice();
    for (let s = 1; s < samples.length; s++) {
      for (let i = 0; i < 6; i++) {
        const v = samples[s][i];
        if (v < mins[i]) mins[i] = v;
        if (v > maxs[i]) maxs[i] = v;
      }
    }
    let moveMaxDeg = 0;
    let moveJoint = 1;
    for (let i = 0; i < 6; i++) {
      const d = Math.abs(maxs[i] - mins[i]) * DEG;
      if (d > moveMaxDeg) { moveMaxDeg = d; moveJoint = i + 1; }
    }
    if (moveMaxDeg > REMOTE_STABLE_MAX_DEG) {
      toast('预检失败：数据源在动 J' + moveJoint + ' Δ=' + moveMaxDeg.toFixed(2) + '°');
      showRemoteDiffLog(
        'source not still over ' + REMOTE_PRECHECK_S + 's\n'
          + 'max peak-to-peak: J' + moveJoint + ' = ' + moveMaxDeg.toFixed(3) + '° (limit ' + REMOTE_STABLE_MAX_DEG + '°)'
      );
      paintRemoteHint();
      return;
    }

    const remoteJ = (Array.isArray(st.joints) ? st.joints : samples[samples.length - 1]).slice(0, 6);
    const hwJ = hardwareJoints(arm);
    if (!hwJ) {
      toast('预检失败：无硬件关节读数');
      paintRemoteHint();
      return;
    }
    const rows = jointDiffRows(remoteJ, hwJ);
    const maxAbs = rows.length ? rows[0].abs : Infinity;
    if (!(maxAbs < REMOTE_SEND_MAX_DELTA_DEG)) {
      const dump = formatRemoteDiffFail(remoteJ, rows);
      console.warn('[remote-precheck] max|Δ|=' + maxAbs.toFixed(3) + '° >= ' + REMOTE_SEND_MAX_DELTA_DEG + '°\n' + dump);
      showRemoteDiffLog(dump);
      toast('预检失败：最大关节差 ' + maxAbs.toFixed(2) + '° ≥ ' + REMOTE_SEND_MAX_DELTA_DEG + '°（见差异表）');
      st.sendReady = false;
      st.queuedJoints = null;
      paintRemoteHint();
      return;
    }

    st.sendReady = true;
    st.queuedJoints = remoteJ.slice();
    showRemoteDiffLog(
      '预检通过 · max|Δ|=' + maxAbs.toFixed(3) + '° < ' + REMOTE_SEND_MAX_DELTA_DEG + '°\n'
        + 'queued joints: [' + remoteJ.map((x) => Number(x).toFixed(4)).join(', ') + ']'
    );
    toast('预检通过，可远程连续下发');
    paintRemoteHint();
  }

  function enqueueRemoteStreamWrite(armId, joints, step) {
    const st = remoteState(armId);
    if (!st || !st.remoteStreaming || !Array.isArray(joints) || joints.length < 6) return;
    if (step != null && st.lastStreamedStep === step && !st.streamWritePending) return;
    st.streamWritePending = { joints: joints.slice(0, 6), step: step };
    if (!st.streamWriteInFlight) flushRemoteStreamWrite(armId);
  }

  async function flushRemoteStreamWrite(armId) {
    const st = remoteState(armId);
    if (!st || st.streamWriteInFlight) return;
    const arm = arms.find((a) => a.id === armId) || null;
    while (st.remoteStreaming && st.streamWritePending) {
      if (!arm || !arm.connected || !isArmed(arm)) {
        stopRemoteStreaming(armId);
        st.sendReady = false;
        toast('连接/Arm 断开，已停止远程连续下发');
        paintRemoteHint();
        return;
      }
      const job = st.streamWritePending;
      st.streamWritePending = null;
      st.streamWriteInFlight = true;
      try {
        const body = {
          arm_id: armId,
          joints_rad: job.joints,
          // CS: runtime maps teleop/direct → servoj_once dense writeServoj.
          timing: 'teleop',
        };
        const r = await fetch('/api/arm/command', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }).then((x) => x.json());
        if (!st.remoteStreaming) return;
        if (!r || !r.ok) {
          stopRemoteStreaming(armId);
          st.sendReady = false;
          toast((r && r.error) || '远程连续下发失败，已停止');
          paintRemoteHint();
          return;
        }
        st.lastStreamedStep = job.step;
      } catch (e) {
        if (!st.remoteStreaming) return;
        stopRemoteStreaming(armId);
        st.sendReady = false;
        toast('远程连续下发异常: ' + (e && e.message ? e.message : e));
        paintRemoteHint();
        return;
      } finally {
        st.streamWriteInFlight = false;
      }
    }
  }

  async function remoteSendActive() {
    const arm = activeArm();
    if (!arm) return;
    const st = remoteState(arm.id);
    // Toggle off
    if (st.remoteStreaming) {
      stopRemoteStreaming(arm.id);
      st.sendReady = false;
      st.queuedJoints = null;
      toast('已停止远程连续下发（需重新预下发）');
      paintRemoteHint();
      return;
    }
    if (!arm.connected) { toast('请先连接机械臂'); return; }
    if (!isArmed(arm)) { toast('请先 Arm 使能'); return; }
    if (!st.on) { toast('请先拉取远程'); return; }
    if (!st.sendReady) {
      toast('请先预下发并通过');
      return;
    }
    if (!Array.isArray(st.joints) || st.joints.length < 6) {
      toast('尚无远程关节帧');
      return;
    }
    // Start continuous direct stream (no abs-ramp).
    st.remoteStreaming = true;
    st.lastStreamedStep = null;
    st.streamWritePending = null;
    paintRemoteButtons();
    paintRemoteHint();
    toast('远程连续下发已开始（稠密 servoj_once）');
    enqueueRemoteStreamWrite(arm.id, st.joints, st.step);
  }

  async function disarmActiveArm(opts) {
    opts = opts || {};
    const a = activeArm();
    if (!a) return { ok: false, error: 'no arm' };
    // Disarm also kills remote continuous-send / in-flight precheck immediately.
    clearRemoteSendGate(a.id, opts.silent ? '' : '已 Disarm，远程连续下发已禁用');
    showRemoteDiffLog('');
    try {
      await fetch('/api/arm/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ arm_id: a.id, cancel_abs_ramp: true }),
      });
    } catch (_) {}
    const r = await fetch('/api/arm/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ arm_id: a.id, disarm: true }),
    }).then((x) => x.json()).catch((e) => ({ ok: false, error: String(e) }));
    // Optimistic UI: write-agent frame may lag one tick.
    if (r && r.ok && a.write_agent) {
      const fr = framesByAgent[a.write_agent] || { agent_id: a.write_agent, payload: {} };
      fr.payload = Object.assign({}, fr.payload || {}, { armed: false });
      framesByAgent[a.write_agent] = fr;
    }
    paintArmButtons();
    paintRemoteButtons();
    return r;
  }

  function stopRemote(armId, opts) {
    opts = opts || {};
    const st = remoteState(armId);
    if (!st) return;
    if (st.es) {
      try { st.es.close(); } catch (_) {}
      st.es = null;
    }
    if (st.pollTimer) {
      clearInterval(st.pollTimer);
      st.pollTimer = null;
    }
    st.on = false;
    st.mode = '';
    st.sendReady = false;
    st.queuedJoints = null;
    st.prechecking = false;
    st.precheckToken = (st.precheckToken || 0) + 1;
    stopRemoteStreaming(armId);
    if (!opts.keepJoints) st.joints = null;
    if (armId === activeId) {
      showRemoteDiffLog('');
      paintRemoteHint();
      paintJoints();
      paintRead();
    }
  }

  function streamUrlFor(raw) {
    let u;
    try { u = new URL(String(raw || '').trim()); }
    catch (_) { return null; }
    if (!u.searchParams.has('stream')) u.searchParams.set('stream', '1');
    if (!u.searchParams.has('hz')) u.searchParams.set('hz', '20');
    return u.toString();
  }

  function startRemotePoll(armId, baseUrl) {
    const st = remoteState(armId);
    st.mode = 'poll';
    const tick = async () => {
      if (!st.on) return;
      try {
        const r = await fetch(baseUrl, { cache: 'no-store' });
        const obj = await r.json();
        applyRemoteFrame(armId, obj);
      } catch (e) {
        if (armId === activeId) {
          const el = $('remoteHint');
          if (el) {
            el.textContent = '远程 poll 失败: ' + (e && e.message ? e.message : e);
            el.className = 'hint remote-hint-err';
          }
        }
      }
    };
    tick();
    st.pollTimer = setInterval(tick, 50);
  }

  function startRemoteStream(armId, url) {
    const st = remoteState(armId);
    const sseUrl = streamUrlFor(url);
    if (!sseUrl) {
      toast('远程 URL 无效');
      return;
    }
    stopRemote(armId, { keepJoints: true });
    st.url = String(url || '').trim();
    st.on = true;
    st.mode = 'sse';
    paintRemoteHint();
    let es;
    try {
      es = new EventSource(sseUrl);
    } catch (e) {
      startRemotePoll(armId, st.url);
      return;
    }
    st.es = es;
    const onPayload = (ev) => {
      try {
        const obj = JSON.parse(ev.data);
        applyRemoteFrame(armId, obj);
      } catch (_) {}
    };
    es.addEventListener('gello', onPayload);
    es.onmessage = onPayload;
    es.onerror = () => {
      // Fall back to HTTP poll if SSE blocked / dropped.
      if (st.es) {
        try { st.es.close(); } catch (_) {}
        st.es = null;
      }
      if (st.on && !st.pollTimer) {
        startRemotePoll(armId, st.url);
        if (armId === activeId) toast('SSE 不可用，已改 poll');
      }
    };
  }

  async function remoteConnectActive() {
    const arm = activeArm();
    if (!arm) return;
    const urlEl = $('remoteUrl');
    const url = (urlEl && urlEl.value ? urlEl.value : '').trim();
    if (!url) { toast('请输入远程 joints URL'); return; }
    try {
      // Validate URL shape early.
      // eslint-disable-next-line no-new
      new URL(url);
    } catch (_) {
      toast('远程 URL 无效');
      return;
    }
    try { localStorage.setItem(LS_REMOTE_URL + arm.id, url); } catch (_) {}
    const st = remoteState(arm.id);
    st.url = url;
    st.sendReady = false;
    st.queuedJoints = null;
    showRemoteDiffLog('');
    startRemoteStream(arm.id, url);
    // Auto disarm once after remote connect (safety); also clears remote-send gate.
    const r = await disarmActiveArm({ silent: true });
    toast(r.ok ? '远程已拉取 · 已自动 Disarm' : ('远程已拉取 · Disarm: ' + (r.error || '失败')));
    paintRemoteHint();
  }

  function remoteDisconnectActive() {
    const arm = activeArm();
    if (!arm) return;
    stopRemote(arm.id);
    toast('已停止远程拉取');
  }

  function paintReadRemoteOverlay() {
    const arm = activeArm();
    const box = $('jointRead');
    if (!arm || !box) return;
    const st = remoteState(arm.id);
    if (!st || !st.on || !Array.isArray(st.joints)) return;
    const n = arm.num_joints || 6;
    let html = '<p class="hint remote-hint-ok">远程 joints · step=' + (st.step != null ? st.step : '—') + '</p>';
    for (let i = 0; i < n; i++) {
      const rad = Number(st.joints[i] || 0);
      const deg = rad * DEG;
      const pct = Math.max(0, Math.min(100, 50 + (deg / 180) * 50));
      html += '<div class="joint"><span>J' + (i + 1) + '</span><div class="bar"><i style="width:' + pct + '%"></i></div><span>' + deg.toFixed(1) + '°</span></div>';
    }
    box.innerHTML = html;
  }

  function currentJoints() {
    const arm = activeArm();
    if (!arm) return null;
    const rst = remoteState(arm.id);
    if (rst && rst.on && Array.isArray(rst.joints)) return rst.joints;
    if (!arm.connected) return null;
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
  function currentFlangePose() {
    const arm = activeArm();
    if (!arm || !arm.connected) return null;
    const fr = framesByAgent[arm.read_agent];
    const p = fr && fr.payload && fr.payload.flange_xyzrpy;
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
    return [0, 1, 2].map((i) => Number(arr[i]).toFixed(4)).join('; ');
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
        : (on ? ('已连接 · ' + (arm.label || arm.id) + (isArmed(arm) ? ' · Armed' : ' · Disarmed')) : ('未连接 · ' + (arm.label || arm.id) + ' — 点「连接」打开读写'));
    }
    paintArmButtons();
    paintArmMaxDelta();
    syncJogDeltaMax();
    // Restore per-cell remote URL from memory / localStorage when switching arms.
    const urlEl = $('remoteUrl');
    if (arm && urlEl && document.activeElement !== urlEl) {
      const st = remoteState(arm.id);
      if (!st.url) {
        try {
          const saved = localStorage.getItem(LS_REMOTE_URL + arm.id);
          if (saved) st.url = saved;
        } catch (_) {}
      }
      if (!st.url) st.url = 'http://127.0.0.1:7020/joints';
    }
    // Drop send gate if connection/arm lost.
    if (arm) {
      const st = remoteState(arm.id);
      if (st && st.sendReady && (!on || !isArmed(arm))) {
        clearRemoteSendGate(arm.id, '状态变化，需重新预下发');
      }
    }
    paintRemoteHint();
  }

  let maxDeltaDirty = false;

  function syncJogDeltaMax() {
    const arm = activeArm();
    const el = $('deltaDeg');
    if (!el) return;
    // While editing maxΔ, don't fight the user with jog-cap clamps from stale arm.*.
    if (maxDeltaDirty || document.activeElement === $('armMaxDelta')) return;
    const cap = (arm && arm.max_delta_deg != null && Number.isFinite(Number(arm.max_delta_deg)))
      ? Number(arm.max_delta_deg)
      : 15;
    el.max = String(cap);
    el.setAttribute('max', String(cap));
    const cur = Number(el.value);
    if (Number.isFinite(cur) && cur > cap) el.value = String(cap);
    el.title = '单次点动角度；不可超过本臂最大角度偏差 ' + cap + '°';
  }

  function paintArmMaxDelta(opts) {
    opts = opts || {};
    const arm = activeArm();
    const inp = $('armMaxDelta');
    const btn = $('btnMaxDeltaApply');
    if (!inp) return;
    if (!arm) {
      inp.value = '';
      inp.disabled = true;
      if (btn) btn.disabled = true;
      maxDeltaDirty = false;
      return;
    }
    inp.disabled = false;
    if (btn) btn.disabled = false;
    inp.title = (arm.label || arm.id) + ' · max_delta_deg（仅本臂；改完点「应用」写入驱动）';
    // WS/paintConn runs at viz_hz — never overwrite while typing / dirty.
    if (!opts.force && (maxDeltaDirty || document.activeElement === inp)) return;
    const deg = arm.max_delta_deg;
    if (deg != null && Number.isFinite(Number(deg))) {
      inp.value = String(Number(Number(deg).toFixed(2)));
    }
  }

  async function refreshArmMaxDeltaFromServer() {
    const arm = activeArm();
    if (!arm) return;
    try {
      const r = await fetch('/api/arm/max-delta?arm_id=' + encodeURIComponent(arm.id)).then((x) => x.json());
      if (r && r.ok && r.max_delta_deg != null) {
        arm.max_delta_deg = r.max_delta_deg;
        maxDeltaDirty = false;
        paintArmMaxDelta({ force: true });
        syncJogDeltaMax();
      }
    } catch (_) {}
  }

  async function applyArmMaxDelta() {
    const arm = activeArm();
    if (!arm) { toast('请先选择臂'); return; }
    const inp = $('armMaxDelta');
    const deg = Number(inp && inp.value);
    if (!Number.isFinite(deg) || deg <= 0) { toast('最大角度偏差须 > 0'); return; }
    if (deg > 180) { toast('最大角度偏差须 ≤ 180°'); return; }
    const r = await fetch('/api/arm/max-delta', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ arm_id: arm.id, max_delta_deg: deg }),
    }).then((x) => x.json());
    if (!r || !r.ok) {
      toast((r && r.error) || '设置失败');
      return;
    }
    arm.max_delta_deg = r.max_delta_deg;
    maxDeltaDirty = false;
    paintArmMaxDelta({ force: true });
    syncJogDeltaMax();
    toast((arm.label || arm.id) + ' 最大Δ° = ' + Number(r.max_delta_deg).toFixed(2) + '（已写入驱动）');
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
  /** Match setTcpPose / applyDragPoseToMarker euler mapping. */
  function robotRpyToThreeEuler(rx, ry, rz) {
    return { x: Number(rx) || 0, y: Number(rz) || 0, z: -(Number(ry) || 0) };
  }
  function threeEulerToRobotRpy(ex, ey, ez) {
    return { rx: ex, ry: -ez, rz: ey };
  }
  function wrapPi(a) {
    let x = a;
    while (x > Math.PI) x -= 2 * Math.PI;
    while (x < -Math.PI) x += 2 * Math.PI;
    return x;
  }
  /** Orientation error (rad) via quaternion angle — immune to Euler ±π wrap. */
  function rpyOriErr(a, b) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length < 6 || b.length < 6) return Infinity;
    if (!_tcpTmpE) _tcpTmpE = new THREE.Euler();
    if (!_tcpTmpQ) _tcpTmpQ = new THREE.Quaternion();
    if (!_tcpTmpQ2) _tcpTmpQ2 = new THREE.Quaternion();
    const ea = robotRpyToThreeEuler(a[3], a[4], a[5]);
    const eb = robotRpyToThreeEuler(b[3], b[4], b[5]);
    _tcpTmpE.set(ea.x, ea.y, ea.z, 'XYZ');
    _tcpTmpQ.setFromEuler(_tcpTmpE);
    _tcpTmpE.set(eb.x, eb.y, eb.z, 'XYZ');
    _tcpTmpQ2.setFromEuler(_tcpTmpE);
    return _tcpTmpQ.angleTo(_tcpTmpQ2);
  }
  function formatXyzrpy(arr) {
    if (!Array.isArray(arr) || arr.length < 6) return '—';
    return arr.slice(0, 6).map((x) => Number(x).toFixed(3)).join(', ');
  }
  function applyDragPoseToMarker() {
    if (!tcpMarker || !dragXyzrpy) return;
    const p = robotToThree(dragXyzrpy[0], dragXyzrpy[1], dragXyzrpy[2]);
    tcpMarker.position.set(p.x, p.y, p.z);
    const e = robotRpyToThreeEuler(dragXyzrpy[3], dragXyzrpy[4], dragXyzrpy[5]);
    tcpMarker.rotation.set(e.x, e.y, e.z, 'XYZ');
    tcpMarker.visible = true;
    hasTcp = true;
    updateTcpRotGizmoScale();
  }
  function syncDragRpyFromMarker() {
    if (!tcpMarker || !dragXyzrpy) return;
    if (!_tcpTmpE) _tcpTmpE = new THREE.Euler();
    _tcpTmpE.setFromQuaternion(tcpMarker.quaternion, 'XYZ');
    const r = threeEulerToRobotRpy(_tcpTmpE.x, _tcpTmpE.y, _tcpTmpE.z);
    dragXyzrpy[3] = r.rx;
    dragXyzrpy[4] = r.ry;
    dragXyzrpy[5] = r.rz;
  }
  function updateTcpRotGizmoScale() {
    if (!tcpRotGizmo || !tcpMarker || !camera) return;
    const dist = camera.position.distanceTo(tcpMarker.position);
    // Larger on-screen rings; clamp so they stay pickable when zoomed out.
    const s = Math.max(0.85, Math.min(3.6, dist * 0.55));
    tcpRotGizmo.scale.setScalar(s);
  }
  function buildTcpRotGizmo() {
    if (!tcpMarker || tcpRotGizmo) return;
    tcpRotGizmo = new THREE.Group();
    tcpRotGizmo.name = 'tcpRotGizmo';
    tcpRotRings = [];
    // Torus lies in XY (around +Z). Reorient for X / Y rings.
    const orients = [
      new THREE.Euler(0, Math.PI / 2, 0), // X → YZ plane
      new THREE.Euler(Math.PI / 2, 0, 0), // Y → XZ plane
      new THREE.Euler(0, 0, 0),           // Z → XY plane
    ];
    for (let axis = 0; axis < 3; axis++) {
      const group = new THREE.Group();
      group.name = 'tcpRotAxis' + axis;
      group.rotation.copy(orients[axis]);
      const mat = new THREE.MeshBasicMaterial({
        color: TCP_ROT_COLORS[axis],
        depthTest: true,
        transparent: true,
        opacity: 0.92,
      });
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(TCP_ROT_RING_R, TCP_ROT_TUBE, 10, 64),
        mat,
      );
      ring.userData.tcpRotAxis = axis;
      ring.userData.tcpRotVisual = true;
      const hitMat = new THREE.MeshBasicMaterial({
        visible: false,
        depthTest: true,
      });
      const hit = new THREE.Mesh(
        new THREE.TorusGeometry(TCP_ROT_RING_R, TCP_ROT_HIT_TUBE, 8, 48),
        hitMat,
      );
      hit.userData.tcpRotAxis = axis;
      hit.userData.tcpRotHit = true;
      group.add(ring);
      group.add(hit);
      tcpRotGizmo.add(group);
      tcpRotRings.push(ring, hit);
    }
    tcpMarker.add(tcpRotGizmo);
  }
  function setTcpRotGizmoVisible(on) {
    if (tcpRotGizmo) tcpRotGizmo.visible = !!on;
  }
  function highlightTcpRotAxis(axisIdx) {
    if (!tcpRotGizmo) return;
    tcpRotGizmo.children.forEach((group, i) => {
      const ring = group.children && group.children[0];
      if (!ring || !ring.material) return;
      const active = (axisIdx === i);
      ring.material.opacity = active ? 1.0 : 0.78;
      ring.material.color.setHex(TCP_ROT_COLORS[i]);
      if (active) ring.scale.setScalar(1.08);
      else ring.scale.setScalar(1.0);
    });
  }
  function pickTcpRotRing(ev) {
    if (!tcpMarker || !tcpMarker.visible || !renderer || !camera) return null;
    if (!tcpRotGizmo || !tcpRotGizmo.visible) return null;
    if (!_tcpRaycaster) _tcpRaycaster = new THREE.Raycaster();
    if (!_tcpNdc) _tcpNdc = new THREE.Vector2();
    const canvas = renderer.domElement;
    const rect = canvas.getBoundingClientRect();
    _tcpNdc.x = ((ev.clientX - rect.left) / Math.max(1, rect.width)) * 2 - 1;
    _tcpNdc.y = -((ev.clientY - rect.top) / Math.max(1, rect.height)) * 2 + 1;
    _tcpRaycaster.setFromCamera(_tcpNdc, camera);
    _tcpRaycaster.params.Line = _tcpRaycaster.params.Line || {};
    const hits = _tcpRaycaster.intersectObjects(tcpRotRings, false);
    if (!hits.length) return null;
    const axis = hits[0].object.userData.tcpRotAxis;
    if (axis == null) return null;
    return { axis: Number(axis), point: hits[0].point };
  }
  function worldAxisForTcpRot(axisIdx) {
    if (!_tcpTmpV) _tcpTmpV = new THREE.Vector3();
    const local = axisIdx === 0 ? _tcpTmpV.set(1, 0, 0)
      : (axisIdx === 1 ? _tcpTmpV.set(0, 1, 0) : _tcpTmpV.set(0, 0, 1));
    return local.clone().transformDirection(tcpMarker.matrixWorld).normalize();
  }
  function angleAroundTcpAxis(clientX, clientY, axisWorld) {
    if (!tcpMarker || !camera || !renderer) return null;
    if (!_tcpRaycaster) _tcpRaycaster = new THREE.Raycaster();
    if (!_tcpNdc) _tcpNdc = new THREE.Vector2();
    if (!_tcpHitPlane) _tcpHitPlane = new THREE.Plane();
    if (!_tcpHitPt) _tcpHitPt = new THREE.Vector3();
    if (!_tcpTmpV2) _tcpTmpV2 = new THREE.Vector3();
    if (!_tcpTmpV3) _tcpTmpV3 = new THREE.Vector3();
    const canvas = renderer.domElement;
    const rect = canvas.getBoundingClientRect();
    _tcpNdc.x = ((clientX - rect.left) / Math.max(1, rect.width)) * 2 - 1;
    _tcpNdc.y = -((clientY - rect.top) / Math.max(1, rect.height)) * 2 + 1;
    _tcpRaycaster.setFromCamera(_tcpNdc, camera);
    const origin = _tcpTmpV2;
    tcpMarker.getWorldPosition(origin);
    _tcpHitPlane.setFromNormalAndCoplanarPoint(axisWorld, origin);
    if (!_tcpRaycaster.ray.intersectPlane(_tcpHitPlane, _tcpHitPt)) return null;
    const v = _tcpHitPt.clone().sub(origin);
    if (v.lengthSq() < 1e-12) return null;
    const ref = Math.abs(axisWorld.dot(_tcpTmpV3.set(0, 1, 0))) < 0.9
      ? _tcpTmpV3.set(0, 1, 0)
      : _tcpTmpV3.set(1, 0, 0);
    const t = new THREE.Vector3().crossVectors(axisWorld, ref).normalize();
    const b = new THREE.Vector3().crossVectors(axisWorld, t).normalize();
    return Math.atan2(v.dot(b), v.dot(t));
  }
  function applyTcpRotationDelta(dAng) {
    /** Integrate a local-axis angle step onto the amber ball (no IK). */
    if (!tcpMarker || !dragXyzrpy || !Number.isFinite(dAng) || Math.abs(dAng) < 1e-12) return;
    if (!_tcpTmpQ) _tcpTmpQ = new THREE.Quaternion();
    if (!_tcpTmpV) _tcpTmpV = new THREE.Vector3();
    const axis = tcpRotAxis === 0 ? _tcpTmpV.set(1, 0, 0)
      : (tcpRotAxis === 1 ? _tcpTmpV.set(0, 1, 0) : _tcpTmpV.set(0, 0, 1));
    _tcpTmpQ.setFromAxisAngle(axis, dAng);
    tcpMarker.quaternion.multiply(_tcpTmpQ);
    tcpMarker.updateMatrixWorld(true);
    syncDragRpyFromMarker();
  }
  function applyTcpRotImpulse(dAng) {
    /** Pointer Δangle → residual ω for coast after release (mass slider). */
    if (!Number.isFinite(dAng) || Math.abs(dAng) < 1e-9) return;
    const mass = Math.max(TCP_MASS_MIN, getTcpMass());
    dragRotVel += (dAng * TCP_ROT_IMPULSE) / mass;
    if (dragRotVel > TCP_OMEGA_MAX) dragRotVel = TCP_OMEGA_MAX;
    if (dragRotVel < -TCP_OMEGA_MAX) dragRotVel = -TCP_OMEGA_MAX;
  }
  function applyTcpRotPointerDelta(dAng) {
    /**
     * While finger is down: mostly follow the pointer (visible feedback),
     * and stash a bit of ω so release still coasts with damping.
     */
    if (!Number.isFinite(dAng) || Math.abs(dAng) < 1e-9) return;
    const direct = dAng * TCP_ROT_DIRECT;
    const coast = dAng * (1 - TCP_ROT_DIRECT);
    applyTcpRotationDelta(direct);
    applyTcpRotImpulse(coast);
    const axName = tcpRotAxis === 0 ? 'X' : (tcpRotAxis === 1 ? 'Y' : 'Z');
    setDragStatus('', '旋转 ' + axName + ' · 目标 ' + formatXyzrpy(dragXyzrpy) + ' · 求解中…');
    scheduleIk(false);
  }
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
    tcpDragMode = 'translate';
    highlightTcpRotAxis(-1);
    if (dragVelThree) dragVelThree.set(0, 0, 0);
    dragRotVel = 0;
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
    // Drag done → snap back to live FK follow (no hold / no「恢复跟随」).
    resumeLiveTcpFollow();
  }
  function maybeAutoResumeAfterDrag() {
    if (!tcpDragActive || tcpPointerDown) return;
    if (dragVelThree && dragVelThree.lengthSq() > 1e-10) return;
    if (Math.abs(dragRotVel) > 1e-4) return;
    if (ikInFlight || ikPending || tcpAutoSendAfterIk || tcpAutoSendInFlight) return;
    // Rotate: never auto-snap back to live — otherwise a successful IK instantly
    // restores the old pose and feels like "rotation has no feedback".
    // User closes the drag panel (×) to resume live follow.
    if (tcpDragMode === 'rotate') return;
    resumeLiveTcpFollow();
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
      else maybeAutoResumeAfterDrag();
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
    let bestScore = -1;
    robot.traverse((obj) => {
      if (!obj || !obj.isObject3D) return;
      const name = String(obj.name || '');
      if (!name) return;
      let score = 0;
      if (/gripper_centor_link|gripper_center_link/i.test(name)) score = 200;
      else if (/gripper_centor|gripper_center/i.test(name)) score = 150;
      else if (/^flan$|tool0|^tcp$|ee_link/i.test(name)) score = 80;
      else if (/ft_kwr75_link/i.test(name)) score = 40;
      else if (/^link6$/i.test(name)) score = 10;
      if (score > bestScore) { bestScore = score; best = obj; }
    });
    return best;
  }
  /** Live follow: parent amber ball to URDF tip (local 0) so it cannot float vs mesh. */
  function attachTcpMarkerToUrdfTip() {
    if (!tcpMarker || !robot) return false;
    const tip = findUrdfTcpObject();
    if (!tip) return false;
    robot.updateMatrixWorld(true);
    if (tcpMarker.parent !== tip) tip.add(tcpMarker);
    tcpMarker.position.set(0, 0, 0);
    tcpMarker.quaternion.identity();
    tcpMarker.visible = true;
    hasTcp = true;
    setTcpRotGizmoVisible(true);
    updateTcpRotGizmoScale();
    return true;
  }
  /** Drag / FK pose: ball must live in scene root with Three-frame xyz. */
  function detachTcpMarkerToScene() {
    if (!tcpMarker || !scene) return;
    if (tcpMarker.parent === scene) return;
    tcpMarker.updateMatrixWorld(true);
    const w = new THREE.Vector3();
    const q = new THREE.Quaternion();
    tcpMarker.getWorldPosition(w);
    tcpMarker.getWorldQuaternion(q);
    scene.add(tcpMarker);
    tcpMarker.position.copy(w);
    tcpMarker.quaternion.copy(q);
  }
  function setTcpPose(xyzrpy, opts) {
    opts = opts || {};
    if (!tcpMarker) return false;
    if (!opts.force && (tcpDragActive || tcpPreviewHold)) return false;
    const xyz = parseXyz(xyzrpy);
    if (!xyz) return false;
    detachTcpMarkerToScene();
    const p = robotToThree(xyz.x, xyz.y, xyz.z);
    tcpMarker.position.set(p.x, p.y, p.z);
    const rx = Number(xyzrpy[3]), ry = Number(xyzrpy[4]), rz = Number(xyzrpy[5]);
    if ([rx, ry, rz].every(Number.isFinite)) tcpMarker.rotation.set(rx, rz, -ry, 'XYZ');
    tcpMarker.visible = true;
    hasTcp = true;
    setTcpRotGizmoVisible(true);
    updateTcpRotGizmoScale();
    if (!opts.skipTrail) pushTrailWaypoint(p.x, p.y, p.z);
    return true;
  }
  function setFlangePose(xyzrpy) {
    if (!flangeMarker) return false;
    const xyz = parseXyz(xyzrpy);
    if (!xyz) {
      flangeMarker.visible = false;
      return false;
    }
    const p = robotToThree(xyz.x, xyz.y, xyz.z);
    flangeMarker.position.set(p.x, p.y, p.z);
    const rx = Number(xyzrpy[3]), ry = Number(xyzrpy[4]), rz = Number(xyzrpy[5]);
    if ([rx, ry, rz].every(Number.isFinite)) flangeMarker.rotation.set(rx, rz, -ry, 'XYZ');
    flangeMarker.visible = true;
    return true;
  }
  function syncTcpMarkerFromUrdf() {
    if (tcpDragActive || tcpPreviewHold || !tcpMarker || !robot) return false;
    if (!attachTcpMarkerToUrdfTip()) return false;
    tcpMarker.updateMatrixWorld(true);
    const w = new THREE.Vector3();
    tcpMarker.getWorldPosition(w);
    pushTrailWaypoint(w.x, w.y, w.z);
    return true;
  }
  function syncFlangeMarkerFromLive() {
    const flange = currentFlangePose();
    if (flange && setFlangePose(flange)) return;
    if (flangeMarker) flangeMarker.visible = false;
  }
  function syncFlangeMarkerFromIkCartesian(cart) {
    // Blue ball follows flange of the joints currently being previewed / commanded.
    if (!cart || !Array.isArray(cart.flange_xyzrpy)) return false;
    return setFlangePose(cart.flange_xyzrpy);
  }
  function syncTcpMarkerFromLive() {
    // During drag/hold the amber ball is the IK target; do NOT reset blue ball from
    // live WS flange (that freezes it until「恢复跟随」). Blue is updated from IK FK.
    if (tcpDragActive || tcpPreviewHold) return;
    // Amber = FK TCP (cartesian_xyzrpy). Blue = FK flange (flange_xyzrpy, tool offset 0).
    // Cell B: amber=TCP (EFG tip), blue=flange; URDF joints from teach MDH.
    const pose = currentPose();
    if (pose && setTcpPose(pose)) {
      syncFlangeMarkerFromLive();
      return;
    }
    if (syncTcpMarkerFromUrdf()) {
      syncFlangeMarkerFromLive();
      return;
    }
    if (tcpMarker) { tcpMarker.visible = false; hasTcp = false; }
    setTcpRotGizmoVisible(false);
    syncFlangeMarkerFromLive();
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
    if (!_tcpTmpE) _tcpTmpE = new THREE.Euler();
    _tcpTmpE.setFromQuaternion(tcpMarker.quaternion, 'XYZ');
    const r = threeEulerToRobotRpy(_tcpTmpE.x, _tcpTmpE.y, _tcpTmpE.z);
    return [rob.x, rob.y, rob.z, r.rx, r.ry, r.rz];
  }
  function beginTcpDrag() {
    // Leaving a held preview: continue from held ball / joints.
    tcpPreviewHold = false;
    // Ball was parented to URDF tip for live follow — detach before free drag.
    detachTcpMarkerToScene();
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
    if (tcpDragMode !== 'rotate') dragRotVel = 0;
    openTcpDragPanel();
    // Snap ball + rings to the IK seed pose (FK frame) so drag deltas stay consistent.
    applyDragPoseToMarker();
    setTcpRotGizmoVisible(true);
    tcpDragActive = true;
    if (tcpDragMode !== 'rotate') tcpRotOriOk = true;
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
      const targetXyzrpy = dragXyzrpy.slice(0, 6);
      const body = { arm_id: arm.id, xyzrpy: targetXyzrpy };
      if (Array.isArray(seed) && seed.length >= 6) body.seed_joints_rad = seed.slice(0, 6).map(Number);
      // Rotate drag needs IK to respect orientation (translate path uses low ori_weight).
      if (tcpDragMode === 'rotate') {
        body.ori_weight = 1.25;
        body.orientation_tolerance_rad = 0.04;
        body.accept_residual = 8e-3;
      }
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
        const achieved = r.cartesian && r.cartesian.cartesian_xyzrpy;
        const oriErr = Array.isArray(achieved) ? rpyOriErr(targetXyzrpy, achieved) : Infinity;
        if (tcpDragMode === 'rotate') {
          // Keep user target rpy — do NOT clobber with position-only FK (old bug).
          // Keep marker on target while dragging / until ori converges.
          applyDragPoseToMarker();
          syncFlangeMarkerFromIkCartesian(r.cartesian);
          const posErr = (r.pos_err_m != null) ? (' · |Δp|=' + Number(r.pos_err_m).toFixed(4) + 'm') : '';
          const oriTxt = ' · |Δrpy|=' + (Number.isFinite(oriErr) ? oriErr.toFixed(3) : '?') + 'rad';
          if (oriErr > 0.08) {
            tcpRotOriOk = false;
            tcpAutoSendAfterIk = false;
            setDragStatus('err', 'IK 姿态未跟上' + oriTxt + posErr + ' · 目标 ' + formatXyzrpy(targetXyzrpy));
          } else {
            tcpRotOriOk = true;
            // Converged enough: optionally snap rpy to achieved for consistency.
            if (Array.isArray(achieved) && achieved.length >= 6) {
              for (let i = 3; i < 6; i++) {
                const v = Number(achieved[i]);
                if (Number.isFinite(v)) dragXyzrpy[i] = v;
              }
              applyDragPoseToMarker();
            }
            const auto = isTcpAutoSendOn();
            setDragStatus('ok', 'IK ok' + oriTxt + posErr + (auto ? ' · 准备下发' : ' · 仅预览'));
            if (auto) queueTcpIkSend();
          }
        } else {
          // Translate: refresh rpy from achieved FK so next xyz step stays reachable.
          if (Array.isArray(achieved) && achieved.length >= 6) {
            for (let i = 3; i < 6; i++) {
              const v = Number(achieved[i]);
              if (Number.isFinite(v)) dragXyzrpy[i] = v;
            }
            const e = robotRpyToThreeEuler(dragXyzrpy[3], dragXyzrpy[4], dragXyzrpy[5]);
            tcpMarker.rotation.set(e.x, e.y, e.z, 'XYZ');
          }
          syncFlangeMarkerFromIkCartesian(r.cartesian);
          const posErr = (r.pos_err_m != null) ? (' · |Δp|=' + Number(r.pos_err_m).toFixed(4) + 'm') : '';
          const auto = isTcpAutoSendOn();
          setDragStatus('ok', 'IK ok' + posErr + (auto ? ' · 准备下发' : ' · 仅预览'));
          if (auto) queueTcpIkSend();
        }
      } else {
        tcpAutoSendAfterIk = false;
        setDragStatus('err', 'IK 失败: ' + ((r && r.error) ? String(r.error) : 'unknown'));
      }
    } catch (e) {
      if (tcpDragActive) setDragStatus('err', 'IK 失败: ' + String(e && e.message || e));
    } finally {
      ikInFlight = false;
      if (ikPending && tcpDragActive) { ikPending = false; scheduleIk(true); }
      else maybeAutoResumeAfterDrag();
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
    if (tcpDragMode === 'rotate') {
      // Pointer-down path applies angle in pointermove; here only coast + IK flush.
      if (!tcpPointerDown && Math.abs(dragRotVel) > 1e-6) {
        applyTcpRotationDelta(dragRotVel * dt);
        dragRotVel *= Math.pow(TCP_ROT_DAMP, dt * 60);
        if (Math.abs(dragRotVel) < 1e-5) dragRotVel = 0;
        const axName = tcpRotAxis === 0 ? 'X' : (tcpRotAxis === 1 ? 'Y' : 'Z');
        setDragStatus('', '旋转惯性 ' + axName + ' · 目标 ' + formatXyzrpy(dragXyzrpy));
        scheduleIk(false);
      } else if (ikPending) {
        scheduleIk(true);
      } else if (!tcpPointerDown && !ikInFlight) {
        maybeAutoResumeAfterDrag();
      }
      return;
    }
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
    } else {
      maybeAutoResumeAfterDrag();
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
    buildTcpRotGizmo();
    setTcpRotGizmoVisible(false);
    // Blue = kinematic flange center (FK with tool offset [0,0,0]); not draggable.
    flangeMarker = new THREE.Mesh(
      new THREE.SphereGeometry(FLANGE_MARKER_R, 14, 14),
      new THREE.MeshBasicMaterial({ color: 0x3b82f6, depthTest: true }),
    );
    const flangeAxes = new THREE.AxesHelper(0.04);
    flangeAxes.raycast = function() {};
    flangeMarker.add(flangeAxes);
    flangeMarker.raycast = function() {};
    flangeMarker.visible = false;
    scene.add(flangeMarker);
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
      if (tcpDragMode === 'rotate') {
        canvas._tcpLastPx = ev.clientX;
        canvas._tcpLastPy = ev.clientY;
        tcpMarker.updateMatrixWorld(true);
        const ax = worldAxisForTcpRot(tcpRotAxis);
        const ang = angleAroundTcpAxis(ev.clientX, ev.clientY, ax);
        if (ang != null) {
          let d = ang - tcpRotLastAngle;
          while (d > Math.PI) d -= 2 * Math.PI;
          while (d < -Math.PI) d += 2 * Math.PI;
          tcpRotLastAngle = ang;
          // Immediate follow (visible) + residual ω for damped coast on release.
          applyTcpRotPointerDelta(d);
        }
        ev.preventDefault();
        return;
      }
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
      highlightTcpRotAxis(-1);
      document.removeEventListener('pointermove', onTcpDocMove, true);
      document.removeEventListener('pointerup', endTcpPointer, true);
      document.removeEventListener('pointercancel', endTcpPointer, true);
      if (controls) controls.enabled = true;
      try { if (ev) canvas.releasePointerCapture(ev.pointerId); } catch (_) {}
      if (tcpDragActive) scheduleIk(true);
      // Keep mode until auto-resume; next pointerdown will set again.
      if (!tcpDragActive) tcpDragMode = 'translate';
    }
    canvas.addEventListener('pointerdown', (ev) => {
      if (ev.button !== 0) return;
      const ringHit = pickTcpRotRing(ev);
      if (ringHit) {
        tcpDragMode = 'rotate';
        tcpRotAxis = ringHit.axis;
        tcpRotOriOk = false;
        if (!beginTcpDrag()) {
          tcpDragMode = 'translate';
          return;
        }
        if (dragVelThree) dragVelThree.set(0, 0, 0);
        dragRotVel = 0;
        highlightTcpRotAxis(tcpRotAxis);
        tcpMarker.updateMatrixWorld(true);
        const ax = worldAxisForTcpRot(tcpRotAxis);
        const ang0 = angleAroundTcpAxis(ev.clientX, ev.clientY, ax);
        tcpRotLastAngle = (ang0 == null) ? 0 : ang0;
      } else if (tcpPointerOver(ev)) {
        tcpDragMode = 'translate';
        if (!beginTcpDrag()) return;
        highlightTcpRotAxis(-1);
      } else {
        return;
      }
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
      if (tcpMarker && tcpMarker.visible) updateTcpRotGizmoScale();
      if (controls && controls.enableDamping) controls.update();
      renderer.render(scene, camera);
    })();
  }

  function clearRobot() {
    if (tcpDragActive || tcpPreviewHold) resumeLiveTcpFollow();
    detachTcpMarkerToScene();
    if (tcpMarker) tcpMarker.visible = false;
    setTcpRotGizmoVisible(false);
    if (flangeMarker) flangeMarker.visible = false;
    hasTcp = false;
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

  /** Catalog ``gripper_rpy`` [rx,ry,rz] rad (URDF XYZ) — assembly-only mesh twist. */
  function applyGripperAssemblyRpy(robotRoot, arm) {
    const rpy = arm && arm.gripper_rpy;
    if (!robotRoot || !Array.isArray(rpy) || rpy.length < 3) return;
    const rx = Number(rpy[0]) || 0;
    const ry = Number(rpy[1]) || 0;
    const rz = Number(rpy[2]) || 0;
    if (![rx, ry, rz].some((v) => Math.abs(v) > 1e-12)) return;
    const links = robotRoot.links || {};
    const link =
      links.gripper_centor_link ||
      links.gripper_center_link ||
      links.ee_link ||
      null;
    if (!link) return;
    const extra = new THREE.Euler(rx, ry, rz, 'XYZ');
    const q = new THREE.Quaternion().setFromEuler(extra);
    link.quaternion.multiply(q);
    link.updateMatrix();
  }

  /** Catalog ``gripper_rpy`` [rx,ry,rz] rad (URDF XYZ) — assembly-only mesh twist. */
  function applyGripperAssemblyRpy(robotRoot, arm) {
    const rpy = arm && arm.gripper_rpy;
    if (!robotRoot || !Array.isArray(rpy) || rpy.length < 3) return;
    const rx = Number(rpy[0]) || 0;
    const ry = Number(rpy[1]) || 0;
    const rz = Number(rpy[2]) || 0;
    if (![rx, ry, rz].some((v) => Math.abs(v) > 1e-12)) return;
    const links = robotRoot.links || {};
    const link =
      links.gripper_centor_link ||
      links.gripper_center_link ||
      links.ee_link ||
      null;
    if (!link) return;
    const extra = new THREE.Euler(rx, ry, rz, 'XYZ');
    const q = new THREE.Quaternion().setFromEuler(extra);
    link.quaternion.multiply(q);
    link.updateMatrix();
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
      applyGripperAssemblyRpy(r, arm);
      robot = r;
      scene.add(robot);
      const keys = robot.joints ? Object.keys(robot.joints) : [];
      $('viewHint').textContent = (arm.label || arm.id) + ' · ' + arm.model
        + ' · joints[' + keys.join(',') + ']'
        + ' · 拖拽旋转 / 琥珀球 IK · TCP 轨迹自动落点';
      paintJoints();
      // Prefer FK pose; fall back to URDF tip if FK warm/profile unavailable.
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
    const rst = remoteState(arm.id);
    let j = null;
    if (rst && rst.on && Array.isArray(rst.joints)) {
      j = rst.joints;
    } else {
      const fr = framesByAgent[arm.read_agent];
      j = fr && fr.payload && fr.payload.joints_rad;
    }
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
        maxDeltaDirty = false;
        renderArmList();
        loadModel(a);
        renderControls();
        paintConn();
        paintRemoteHint();
        paintRead();
        refreshArmMaxDeltaFromServer();
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
    const rst = remoteState(arm.id);
    if (rst && rst.on && Array.isArray(rst.joints)) {
      paintReadRemoteOverlay();
      const jl = $('jointsLine');
      if (jl) jl.textContent = 'joints (remote): ' + (fmtCsv6(rst.joints) || '—');
      $('poseLine').textContent = 'TCP —（远程 joints 驱动画布）';
      const fl = $('flangeLine');
      if (fl) fl.textContent = '法兰 —';
      paintJoints();
      return;
    }
    if (!arm.connected) {
      box.innerHTML = '<p class="hint">未连接 — 关节读数不可用</p>';
      const jl = $('jointsLine');
      if (jl) jl.textContent = 'joints —';
      $('poseLine').textContent = 'TCP —';
      const fl = $('flangeLine');
      if (fl) fl.textContent = '法兰 —';
      if (flangeMarker) flangeMarker.visible = false;
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
    const jl = $('jointsLine');
    if (jl) {
      const csv = fmtCsv6(j);
      jl.textContent = csv ? ('joints (rad): ' + csv) : 'joints —';
    }
    const cart = fr && fr.payload && fr.payload.cartesian_xyzrpy;
    $('poseLine').textContent = Array.isArray(cart)
      ? ('TCP xyzrpy: ' + cart.map(x => Number(x).toFixed(3)).join(', '))
      : 'TCP —';
    const flange = fr && fr.payload && fr.payload.flange_xyzrpy;
    const flEl = $('flangeLine');
    if (flEl) {
      flEl.textContent = Array.isArray(flange)
        ? ('法兰 xyzrpy: ' + flange.map(x => Number(x).toFixed(3)).join(', '))
        : '法兰 —';
    }
    paintArmButtons();
    paintRemoteButtons();
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
    refreshArmMaxDeltaFromServer();

    $('btnMaxDeltaApply').onclick = () => applyArmMaxDelta();
    $('armMaxDelta').addEventListener('input', () => { maxDeltaDirty = true; });
    $('armMaxDelta').addEventListener('change', () => { maxDeltaDirty = true; });
    $('armMaxDelta').addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') applyArmMaxDelta();
    });

    $('btnRemoteConnect').onclick = () => remoteConnectActive();
    $('btnRemoteDisconnect').onclick = () => remoteDisconnectActive();
    $('btnRemotePrecheck').onclick = () => remotePrecheckActive();
    $('btnRemoteSend').onclick = () => remoteSendActive();
    $('remoteUrl').addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') remoteConnectActive();
    });
    $('remoteUrl').addEventListener('change', () => {
      const arm = activeArm();
      if (!arm) return;
      const st = remoteState(arm.id);
      st.url = String($('remoteUrl').value || '').trim();
      try { localStorage.setItem(LS_REMOTE_URL + arm.id, st.url); } catch (_) {}
    });

    $('btnConnect').onclick = async () => {
      const a = activeArm(); if (!a) return;
      resumeLiveTcpFollow();
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
      if (r && r.ok && a.write_agent) {
        const fr = framesByAgent[a.write_agent] || { agent_id: a.write_agent, payload: {} };
        fr.payload = Object.assign({}, fr.payload || {}, { armed: true });
        framesByAgent[a.write_agent] = fr;
      }
      paintArmButtons();
      paintRemoteButtons();
      toast(r.ok ? 'armed' : (r.error || 'arm failed'));
    };
    $('btnDisarm').onclick = async () => {
      const r = await disarmActiveArm();
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
            // Preserve in-progress maxΔ edits: WS arms replace would clobber the input via paintConn.
            const dirtyId = maxDeltaDirty ? activeId : null;
            const dirtyVal = dirtyId ? $('armMaxDelta').value : null;
            arms = msg.arms;
            if (!arms.find((x) => x.id === activeId) && arms[0]) activeId = arms[0].id;
            if (dirtyId && dirtyVal != null) {
              const a = arms.find((x) => x.id === dirtyId);
              // Keep model in sync with what the user is typing until Apply.
              if (a) {
                const n = Number(dirtyVal);
                if (Number.isFinite(n)) a.max_delta_deg = n;
              }
            }
            if (connChanged || prev !== activeId) {
              if (prev !== activeId) maxDeltaDirty = false;
              renderArmList();
            } else paintConn();
            if (dirtyId && dirtyId === activeId && dirtyVal != null && $('armMaxDelta')) {
              $('armMaxDelta').value = dirtyVal;
              maxDeltaDirty = true;
            }
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
    ori_weight: float | None = None
    orientation_tolerance_rad: float | None = None
    accept_residual: float | None = None


class ArmMaxDeltaBody(BaseModel):
    arm_id: str
    max_delta_deg: float


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
        # IK is CPU-bound (scipy LM); keep the event loop free for WS/UI.
        return await asyncio.to_thread(
            orch.arm_ik,
            body.arm_id,
            body.xyzrpy,
            body.seed_joints_rad,
            ori_weight=body.ori_weight,
            orientation_tolerance_rad=body.orientation_tolerance_rad,
            accept_residual=body.accept_residual,
        )

    @app.get("/api/arm/max-delta")
    async def arm_max_delta_get(arm_id: str) -> dict[str, Any]:
        return orch.arm_max_delta_get(arm_id)

    @app.post("/api/arm/max-delta")
    async def arm_max_delta_set(body: ArmMaxDeltaBody) -> dict[str, Any]:
        return orch.arm_max_delta_set(body.arm_id, body.max_delta_deg)

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
