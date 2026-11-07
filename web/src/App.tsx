// 独立图文编辑器：单视图编排（画布 + 右栏属性/AI），没有任何项目管理。
//
// 工作目录由**服务端**决定（`--dir` 绑定），启动时 GET /api/context 拿
// `{dir, name, has_figure}`；URL 的 `?dir=` 只是可选提示（dev 下服务没传 --dir
// 时用于首次绑定），缺省也能直接打开。`?panel=ai` 只渲染 AI 面板的精简布局
// （二期拆到 Index 右栏用）。

import * as React from "react";
import { Workbench } from "./fig-workbench/Workbench";
import { AIPanel } from "./fig-ai/AIPanel";
import { fetchContext, readDirParam, type WorkdirContext } from "./app/context";
import { FIGURE_ID, setApiDir } from "./shared/api";

function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="app-missing">
      <h1>加载工作目录失败</h1>
      <p className="error">{message}</p>
      <button onClick={onRetry}>重试</button>
    </div>
  );
}

export default function App() {
  const params = React.useMemo(() => new URLSearchParams(window.location.search), []);
  const pageDir = readDirParam(params);
  const panelOnly = params.get("panel") === "ai";
  return <StandaloneView pageDir={pageDir} panelOnly={panelOnly} />;
}

function StandaloneView({ pageDir, panelOnly }: { pageDir: string | null; panelOnly: boolean }) {
  const [workdir, setWorkdir] = React.useState<WorkdirContext | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [nonce, setNonce] = React.useState(0);
  // 应用状态：是否有图（AI 面板据此判断可用性；Workbench 加载/AI 运行后回写）
  const [hasFigure, setHasFigure] = React.useState<boolean | null>(null);

  React.useEffect(() => {
    let stale = false;
    setWorkdir(null);
    setError(null);
    setHasFigure(null);
    fetchContext(pageDir)
      .then((c) => {
        if (stale) return;
        setApiDir(c.dir); // 之后所有 /api 请求都带 ?dir=<规范化后的工作目录>
        document.title = c.name;
        setWorkdir(c);
        setHasFigure(c.has_figure);
      })
      .catch((e) => {
        if (!stale) setError((e as Error).message);
      });
    return () => {
      stale = true;
    };
  }, [pageDir, nonce]);

  if (error) return <LoadError message={error} onRetry={() => setNonce((n) => n + 1)} />;
  if (!workdir) return <div className="app-loading">加载中…</div>;

  if (panelOnly) {
    return (
      <div className="fig-scope app-ai-page">
        <div className="fig-header app-ai-header">
          <b>{workdir.name}</b>
          <span className="fig-hint" title={workdir.dir}>
            {workdir.dir}
          </span>
        </div>
        <div className="app-ai-body">
          <AIPanel
            itemId={FIGURE_ID}
            dir={workdir.dir}
            hasFigure={hasFigure}
            onHasFigure={setHasFigure}
          />
        </div>
      </div>
    );
  }

  return (
    <Workbench
      itemId={FIGURE_ID}
      dir={workdir.dir}
      name={workdir.name}
      hasFigure={hasFigure}
      onFigureStateChange={setHasFigure}
    />
  );
}
