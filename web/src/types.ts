// 共享类型定义

export interface FigureInfo {
  name: string;
  hasBase: boolean;
  lastRenderAt: string | null;
  opCount: number;
}

export interface ProjectInfo {
  name: string;
  figures: FigureInfo[];
}

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
  value?: any; // set_style/set_text: string; transform: {translate?, scale?}; set_visible: boolean; reorder: {to: "front"|"back"}
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
  id: string;
  note: string;
}

export interface FigureDetail {
  project: string;
  figure: string;
  meta: { name: string; project?: string; createdAt?: string; lastRenderAt?: string | null } | null;
  code: string | null;
  baseSvg: string | null;
  finalSvg: string | null;
  patch: PatchDoc;
  snapshots: SnapshotInfo[];
  renderError?: string | null;
}

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
  project?: string;
  figure?: string;
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
  phase: "run_start" | "run_end" | "node_start" | "node_end" | "node_failed" | "llm_start" | "llm_end";
  node?: string;
  detail?: string;
  ok?: boolean;
  at: number;
}
