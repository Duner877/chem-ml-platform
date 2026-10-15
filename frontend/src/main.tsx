import React from "react";
import ReactDOM from "react-dom/client";
import { ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./index.css";
import App from "./App";
import { applyTheme, initialTheme } from "./theme";

const root = document.getElementById("root");
if (!root) {
  throw new Error("index.html is missing the #root container");
}

// Paint the starting theme before the first React commit: without this the
// first frame would flash the default (dark) palette in the white theme.
// ``?theme=<id>`` overrides the stored choice (deep link / smoke test).
applyTheme(initialTheme());

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <ReactFlowProvider>
      <App />
    </ReactFlowProvider>
  </React.StrictMode>
);
