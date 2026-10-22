// 共享类型定义（Index 仓库模式：条目 id 寻址）

export interface RepoInfo {
  path: string;
  itemCount: number;
  dbVersion: number;
}

export interface GroupInfo {
  id: number;
  parentId: number | null;
  name: string;
  position: number;
  boundItemId: number | null;
}

export interface TagInfo {
  id: number;
  name: string;
}

export interface FieldInfo {
  id: number;
  name: string;
  fieldType: "text" | "checkbox" | "date" | "number" | "dropdown" | "item";
  position: number;
  label: string;
  options: string[];
}

export interface TypeInfo {
  id: number;
  name: string;
  icon: string;
  fields: FieldInfo[];
}

export interface ItemInfo {
  id: string;
  name: string;
  typeName: string;
  groupIds: number[];
  tags: string[];
  properties: Record<string, string>;
  createdAt: string;
  updatedAt: string;
  hasBase?: boolean;
  lastRenderAt?: string | null;
  opCount?: number;
}

export interface FileInfo {
  path: string;
  isDir: boolean;
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
  id: string;
  name: string;
  properties: Record<string, string>;
  groupIds: number[];
  tags: string[];
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
  item?: string;
  phase: "run_start" | "run_end" | "node_start" | "node_end" | "node_failed" | "llm_start" | "llm_end";
  node?: string;
  detail?: string;
  ok?: boolean;
  at: number;
}
