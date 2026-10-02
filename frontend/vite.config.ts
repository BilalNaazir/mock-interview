// vite.config.ts - Settings for Vite, the tool that runs the dev server
// (npm run dev) and bundles the app for production (npm run build).
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,        // must match CORS_ORIGINS in the backend and the Cognito callback URL
    strictPort: true,  // fail loudly instead of silently using another port
  },
});
