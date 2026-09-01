import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// THREATZONE frontend. Talks to the existing FastAPI backend (main.py) --
// see src/config.js for the API base URL. No physics happens here.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
