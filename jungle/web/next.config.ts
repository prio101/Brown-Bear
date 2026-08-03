import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Traced, self-contained server bundle. Without this the runtime image has to
  // ship all of node_modules, which on a box already running Ollama and
  // ChromaDB is not a rounding error.
  output: "standalone",
  reactStrictMode: true,

  // The dashboard reads live operational numbers. A cached token total is a
  // correctness bug, so nothing here opts into static generation by default.
  //
  // Data fetching happens server-side against BB_API_URL (the FastAPI app on
  // the Docker network). The browser never holds an API credential — see
  // BB-103 and sprint-1 decision D1.
};

export default nextConfig;
