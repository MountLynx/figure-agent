// 前端共享类型（自 itemmanage figurePlugins/shared/types.ts 移植：只留 figures 域面）。

export interface TemplateInfo {
  id: string;
  title: string;
  description: string;
}

export interface TargetRef {
  id: string | null;
  semanticPath: string;
  fingerprint: string;
}

export type OpKind = "set_style" | "set_text" | "transform" | "set_visible" | "reorder";
export type OpStatus = "active" | "resolved" | "lost";

export interface Op {
  id: string;
  kind: OpKind;
  target: TargetRef;
  attr?: string;
  value?: any;
  intent: string;
  origin: "manual" | "ai";
  status: OpStatus;
  pre?: { center?: [number, number]; size?: [number, number] };
}

export interface PatchDoc {
  baseHash: string;
  ops: Op[];
}

export interface SnapshotInfo {
  createdAt: string;
  note: string;
  dir: string;
}

export interface FigureDetail {
  hasFigure: true;
  /** 工作目录（服务端绑定值，与 /api/context 的 dir 同值）。 */
  dir?: string;
  /** 独立服务没有条目 id；字段保留以兼容旧响应，前端一律以 dir/name 为准。 */
  id?: string;
  /** 目录名（服务端给则优先，否则用 /api/context 的 name）。 */
  name?: string;
  properties?: Record<string, string>;
  code: string | null;
  baseSvg: string | null;
  finalSvg: string | null;
  patch: PatchDoc;
  snapshots?: SnapshotInfo[];
  renderError?: string | null;
}

export interface NoFigure {
  hasFigure: false;
  /** 工作目录（服务端绑定值，与 /api/context 的 dir 同值）。 */
  dir?: string;
  id?: string;
  name?: string;
}

export type FigureResponse = FigureDetail | NoFigure;

export interface RenderResult {
  ok: boolean;
  stderr: string;
  errorLine: number | null;
  warnings: string[];
  stats: {
    elementCount?: number;
    semanticGroupCount?: number;
    faGroups?: string[];
    matplotlibGroups?: string[];
  };
}

export interface SelectionJSON {
  elementId: string | null;
  semanticPath: string;
  userSpaceBBox?: { x: number; y: number; w: number; h: number };
  style?: { fill?: string | null; stroke?: string | null };
  text?: { content: string | null; fontFamily: string | null; fontSize: string | null };
  fingerprint?: string;
  nearby?: string[];
  item?: string;
  warnings?: string[];
}

export interface VerifyResponse {
  results: { opId: string; status: string; detail: string }[];
  remainingOps: number;
  cleared: boolean;
}

export interface AiStatus {
  configured: boolean;
  provider: string;
  model: string;
  mock: boolean;
  detail?: string;
}

export interface AiRunResult {
  id?: string;
  kind: "create" | "adapt" | "edit" | "writeback";
  ok: boolean;
  rounds: number;
  stderr: string;
  error_line?: number | null;
  notes?: string;
  cleared?: boolean;
  remaining?: number;
}

export interface RunEvent {
  runId: string;
  /** 旧字段（item 寻址时代）；独立应用不再使用。 */
  item?: string;
  /** 独立应用的事件标识：工作目录（与 /api/context 的 dir 同值）。 */
  dir?: string;
  phase: "run_start" | "run_end" | "node_start" | "node_end" | "node_failed" | "llm_start" | "llm_end";
  node?: string;
  detail?: string;
  ok?: boolean;
  at: number;
}

export interface FileNode {
  name: string;
  is_dir: boolean;
  children?: FileNode[];
}
