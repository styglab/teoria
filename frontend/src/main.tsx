import "@xyflow/react/dist/style.css";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ServerQueryProvider } from "./api/server_queries";
import "./components/ui/design_tokens.css";
import "./components/ui/form_controls.css";
import { PlatformShell } from "./shell/PlatformShell";
import "./shell/workspace_experience.css";
import "./styles.css";
import "./workspace.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ServerQueryProvider>
      <BrowserRouter>
        <PlatformShell />
      </BrowserRouter>
    </ServerQueryProvider>
  </React.StrictMode>,
);
