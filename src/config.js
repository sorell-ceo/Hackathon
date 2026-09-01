// THREATZONE frontend config.
//
// In local dev, Vite runs on :5173 and FastAPI runs on :8000 (see main.py's
// CORS allow_origins list) — so point at that directly.
// In production on Vercel, the FastAPI app is expected to be served from
// the same domain under /api, so a relative path works and needs no change.
export const API_BASE_URL = import.meta.env.DEV ? "http://localhost:8000" : "";
