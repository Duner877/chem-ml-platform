import React from "react";
import ReactDOM from "react-dom/client";
import { ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./index.css";
import App from "./App";

const root = document.getElementById("root");
if (!root) {
  throw new Error("index.html is missing the #root container");
}

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <ReactFlowProvider>
      <App />
    </ReactFlowProvider>
  </React.StrictMode>
);
