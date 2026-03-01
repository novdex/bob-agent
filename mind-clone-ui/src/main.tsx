import React from "react";
import ReactDOM from "react-dom/client";
import { Toaster } from "react-hot-toast";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
    <Toaster
      position="bottom-right"
      toastOptions={{
        duration: 3500,
        style: {
          background: "var(--bg-1, #111a24)",
          color: "var(--text, #e9f2fb)",
          border: "1px solid var(--line, rgba(151,184,211,0.22))",
          borderRadius: "10px",
          fontSize: "0.88rem",
        },
      }}
    />
  </React.StrictMode>,
);
