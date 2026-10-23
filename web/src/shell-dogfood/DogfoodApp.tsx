// shell-react 狗粮视图：把 @index/shell-react 挂到 figure-agent REST 引擎之上。
// 通过 ?view=shell 查询参数进入；挂载时自动打开服务端当前仓库
// （仓库未打开前 AppShell 自身渲染 RepoDashboard）。

import { useEffect } from "react";
import { AppShell, setPlatform } from "@index/shell-react";
import { setEngine } from "@index/stores/pure";
import { useRepoStore } from "@index/stores-react";
import { engineApi } from "./engineApi";
import { platform } from "./platform";

setEngine(engineApi);
setPlatform(platform);

export default function DogfoodApp() {
  useEffect(() => {
    void (async () => {
      try {
        const info = await engineApi.repo.info();
        await useRepoStore.getState().openRepo(info.path);
      } catch (e) {
        console.error("dogfood: auto-open failed", e);
      }
    })();
  }, []);
  return <AppShell config={{ brand: { name: "figure-agent" } }} />;
}
