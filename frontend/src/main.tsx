// main.tsx - The very first code that runs in the browser.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AuthProvider } from "react-oidc-context";
import { BrowserRouter } from "react-router";
import App from "./App";
import { oidcConfig } from "./auth";
import "./index.css";

// The app is wrapped in "providers", each giving every component inside it
// access to something:
//   - AuthProvider:  login state (useAuth() works anywhere inside)
//   - BrowserRouter: page navigation based on the URL
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider {...oidcConfig}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </AuthProvider>
  </StrictMode>,
);
