// fig-* 组件样式（单次注入 <style>；类名一律 fig- 前缀；
// 颜色/圆角/字体全用 shell CSS 变量令牌，自动跟随明暗主题）。

const STYLE_ID = "fig-plugin-styles";

const CSS = `
.fig-scope {
  color: var(--text);
  font-family: var(--font);
  font-size: var(--fs-sm);
  box-sizing: border-box;
}
.fig-scope *, .fig-scope *::before, .fig-scope *::after { box-sizing: border-box; }
.fig-scope button {
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  border-radius: var(--r-sm);
  padding: 4px 10px;
  cursor: pointer;
  font-size: var(--fs-sm);
  font-family: var(--font);
}
.fig-scope button:hover { border-color: var(--accent); color: var(--accent); }
.fig-scope button:disabled { opacity: 0.45; cursor: default; }
.fig-scope button.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-fg); }
.fig-scope button.small { padding: 2px 7px; font-size: var(--fs-xs); }
.fig-scope input[type="text"], .fig-scope input[type="number"], .fig-scope select, .fig-scope textarea {
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 4px 6px;
  font-size: var(--fs-sm);
  width: 100%;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
}
.fig-scope textarea { min-height: 56px; resize: vertical; }
.fig-scope input[type="color"] {
  width: 42px; height: 26px; padding: 0;
  border: 1px solid var(--border); border-radius: var(--r-sm); background: none;
}

/* ---- 工作台布局 ---- */
.fig-workbench-root { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.fig-header {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 6px 10px; background: var(--surface); border-bottom: 1px solid var(--border);
}
.fig-header .toggle {
  display: inline-flex; align-items: center; gap: 4px; user-select: none; cursor: pointer;
  font-size: var(--fs-xs); color: var(--text-muted);
}
.fig-main { flex: 1; display: flex; min-height: 0; }
.fig-col-left { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.fig-col-right {
  width: 320px; flex: none; background: var(--surface); border-left: 1px solid var(--border);
  overflow-y: auto; padding: 10px; display: flex; flex-direction: column; gap: 12px;
}
.fig-bottombar {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  padding: 6px 10px; background: var(--surface); border-top: 1px solid var(--border);
}
.fig-bottombar .spacer { flex: 1; }
/* 底层面板：轻编辑 / 微调 patch / 运行记录 横排（fig-main 之下、全宽） */
.fig-bottompanel {
  display: flex; gap: 12px; align-items: stretch;
  padding: 8px 10px; background: var(--surface); border-top: 1px solid var(--border);
  max-height: 240px; flex: none;
}
.fig-bottompanel .fig-section { flex: 1; min-width: 0; overflow-y: auto; }
.fig-hint { font-size: var(--fs-xs); color: var(--text-muted); line-height: 1.5; }
.fig-ws-state { font-size: var(--fs-xs); color: var(--text-muted); }
.fig-notice {
  margin: 8px 10px 0; padding: 8px 10px; border-radius: var(--r-md);
  font-size: var(--fs-xs); white-space: pre-wrap;
}
.fig-notice.error { background: var(--danger-subtle, rgba(220,38,38,.08)); color: var(--danger); border: 1px solid var(--danger); }
.fig-notice.warn { background: rgba(217,119,6,.08); color: var(--warning); border: 1px solid var(--warning); }

/* ---- Viewer ---- */
.fig-viewer-wrap {
  flex: 1; position: relative; overflow: hidden; min-height: 0;
  background: repeating-conic-gradient(var(--surface-hover) 0% 25%, var(--bg) 0% 50%) 50% / 24px 24px;
}
.fig-viewer-canvas { position: absolute; inset: 0; }
.fig-viewer-canvas svg {
  display: block; width: 100%; height: 100%;
  user-select: none; -webkit-user-select: none;
}
.fig-viewer-wrap .fig-zoom {
  position: absolute; right: 10px; bottom: 10px; display: flex; gap: 6px;
}
.fig-overlay-box {
  position: absolute; pointer-events: none; border-radius: 2px;
  border: 1.5px solid var(--accent); background: color-mix(in srgb, var(--accent) 10%, transparent);
}
.fig-overlay-box .fig-overlay-label {
  position: absolute; top: -18px; left: -1.5px; white-space: nowrap;
  font-size: var(--fs-xs); background: var(--accent); color: var(--accent-fg);
  padding: 1px 6px; border-radius: 3px;
}
.fig-overlay-box.hover-box { border-style: dashed; border-color: var(--text-muted); background: transparent; }
.fig-overlay-box.hover-box .fig-overlay-label { background: var(--text-muted); color: var(--bg); }
svg .fa-selected { outline: 2px solid var(--accent); }

/* ---- 右栏区块 ---- */
.fig-section { display: flex; flex-direction: column; gap: 6px; }
.fig-section > h3 {
  margin: 0 0 4px; padding-bottom: 4px; font-size: var(--fs-sm); font-weight: var(--fw-semibold);
  color: var(--text-muted); border-bottom: 1px solid var(--border);
}
.fig-sel-info {
  font-size: var(--fs-xs); color: var(--text-secondary); word-break: break-all;
  background: var(--bg); border-radius: var(--r-md); padding: 8px;
}
.fig-sel-info b { color: var(--text); }
.fig-sel-lost { color: var(--danger); font-weight: var(--fw-semibold); }

.fig-element-tree { display: flex; flex-direction: column; gap: 1px; }
.fig-element-row {
  display: flex; align-items: center; gap: 3px; font-size: var(--fs-xs);
  padding: 2px 4px; border-radius: var(--r-sm);
}
.fig-element-row:hover { background: var(--surface-hover); }
.fig-element-row.element-active { background: var(--accent-subtle); }
.fig-element-row.element-active .fig-element-name { color: var(--accent); font-weight: var(--fw-semibold); }
.fig-element-name { cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fig-element-name:hover { color: var(--accent); }
.fig-element-row.element-hidden .fig-element-name { color: var(--text-muted); text-decoration: line-through; }
.fig-element-caret { width: 14px; flex: none; text-align: center; }
button.fig-element-caret { padding: 0 2px; border: none; background: none; color: var(--text-muted); cursor: pointer; }
button.fig-element-caret:hover { color: var(--text); border: none; }
.fig-element-btn { padding: 0 4px; font-size: var(--fs-xs); flex: none; }

.fig-edit-grid {
  display: grid; grid-template-columns: auto 1fr; gap: 6px 8px;
  align-items: center; font-size: var(--fs-sm);
}
.fig-edit-grid label { color: var(--text-muted); }

.fig-op-item {
  border: 1px solid var(--border); border-radius: var(--r-md);
  padding: 6px 8px; font-size: var(--fs-xs);
  display: flex; flex-direction: column; gap: 3px;
}
.fig-op-item .fig-op-head { display: flex; align-items: center; gap: 6px; }
.fig-op-item .fig-op-desc { color: var(--text-muted); }
.fig-status-badge { font-size: var(--fs-xs); border-radius: var(--r-full, 8px); padding: 0 7px; font-weight: var(--fw-semibold); }
.fig-status-active { background: var(--accent-subtle); color: var(--accent); }
.fig-status-resolved { background: color-mix(in srgb, var(--success) 15%, transparent); color: var(--success); }
.fig-status-lost { background: color-mix(in srgb, var(--danger) 15%, transparent); color: var(--danger); }

.fig-code {
  background: var(--bg); color: var(--text); border: 1px solid var(--border);
  border-radius: var(--r-md); padding: 10px; margin: 0;
  font-size: var(--fs-xs); font-family: var(--font-mono);
  overflow: auto; max-height: 260px; white-space: pre;
}
.fig-dirty-banner {
  background: rgba(217,119,6,.08); border: 1px solid var(--warning);
  color: var(--warning); padding: 6px 10px; border-radius: var(--r-md); font-size: var(--fs-xs);
}
.fig-kv { display: grid; grid-template-columns: auto 1fr; gap: 2px 8px; font-size: var(--fs-xs); }
.fig-kv .k { color: var(--text-muted); white-space: nowrap; }
.fig-kv .v { word-break: break-all; }
.fig-filelist { font-family: var(--font-mono); font-size: var(--fs-xs); color: var(--text-muted); }
.fig-runlist { list-style: none; margin: 0; padding: 0; font-size: var(--fs-xs); font-family: var(--font-mono); max-height: 200px; overflow-y: auto; }
.fig-run-ev { padding: 1px 0; color: var(--text-secondary); }
.fig-run-ev-run_start, .fig-run-ev-run_end { color: var(--text); font-weight: var(--fw-semibold); }
.fig-run-ev-node_failed { color: var(--danger); }
.fig-run-ev-llm_start, .fig-run-ev-llm_end { color: var(--text-muted); }

/* ---- 建图流 ---- */
.fig-create-flow { max-width: 520px; margin: 40px auto; display: flex; flex-direction: column; gap: 10px; padding: 16px; }
.fig-create-flow h2 { margin: 0; font-size: var(--fs-lg); color: var(--text-heading); }
.fig-tabs { display: flex; gap: 4px; }
.fig-tabs button.active { color: var(--accent); border-color: var(--accent); font-weight: var(--fw-semibold); }
.fig-create-flow label { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-xs); color: var(--text-muted); }
.fig-create-error { color: var(--danger); font-size: var(--fs-xs); white-space: pre-wrap; }

/* ---- toast ---- */
.fig-toast {
  position: absolute; bottom: 14px; left: 50%; transform: translateX(-50%);
  background: var(--text); color: var(--bg);
  padding: 8px 16px; border-radius: var(--r-md); font-size: var(--fs-sm);
  box-shadow: var(--shadow-lg); z-index: 50; white-space: nowrap;
}
.fig-toast.error { background: var(--danger); color: #fff; }

/* ---- fig-ai 面板 ---- */
.fig-ai-root { display: flex; flex-direction: column; gap: 12px; }
.fig-ai-root section { display: flex; flex-direction: column; gap: 6px; }
.fig-ai-root h4 { margin: 0 0 4px; font-size: var(--fs-sm); color: var(--text-heading); }
.fig-ai-status {
  font-size: var(--fs-xs); color: var(--text-secondary); padding: 6px 8px;
  background: var(--bg); border-radius: var(--r-sm);
}
.fig-ai-empty { font-size: var(--fs-sm); color: var(--text-muted); padding: 16px 8px; text-align: center; }
`;

export function injectStyles(): void {
  if (typeof document === "undefined") return;
  let el = document.getElementById(STYLE_ID) as HTMLStyleElement | null;
  if (!el) {
    el = document.createElement("style");
    el.id = STYLE_ID;
    document.head.appendChild(el);
  }
  el.textContent = CSS;
}
