// REST API 客户端

import type {
  FigureDetail,
  PatchDoc,
  ProjectInfo,
  RenderResult,
  SelectionJSON,
  TemplateInfo,
  VerifyResponse,
} from "./types";

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(`${resp.status}: ${detail}`);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  listProjects: () => fetch("/api/projects").then((r) => json<ProjectInfo[]>(r)),

  listTemplates: () => fetch("/api/templates").then((r) => json<TemplateInfo[]>(r)),

  createFigure: (project: string, name: string, template: string) =>
    fetch(`/api/projects/${project}/figures`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, template }),
    }).then((r) => json<{ ok: boolean; stderr: string }>(r)),

  getFigure: (project: string, figure: string) =>
    fetch(`/api/figure/${project}/${figure}`).then((r) => json<FigureDetail>(r)),

  putCode: (project: string, figure: string, code: string) =>
    fetch(`/api/figure/${project}/${figure}/code`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    }).then((r) => json<RenderResult>(r)),

  run: (project: string, figure: string) =>
    fetch(`/api/figure/${project}/${figure}/run`, { method: "POST" }).then((r) =>
      json<RenderResult>(r)
    ),

  putPatch: (project: string, figure: string, patch: PatchDoc) =>
    fetch(`/api/figure/${project}/${figure}/patch`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }).then((r) => json<{ ok: boolean }>(r)),

  verifyPatch: (project: string, figure: string) =>
    fetch(`/api/figure/${project}/${figure}/verify-patch`, { method: "POST" }).then((r) =>
      json<VerifyResponse>(r)
    ),

  snapshot: (project: string, figure: string, note: string) =>
    fetch(`/api/figure/${project}/${figure}/snapshot`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    }).then((r) => json<{ id: string }>(r)),

  pushSelection: (project: string, figure: string, selection: object) =>
    fetch("/api/session/selection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project, figure, selection }),
    }).then((r) => json<SelectionJSON>(r)),
};
