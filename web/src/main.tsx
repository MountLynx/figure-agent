import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { injectStyles } from "./shared/styles";
import "./styles.css";

// fig-* 组件样式（原插件的样式注入，单次 <style>）
injectStyles();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
