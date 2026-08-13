import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Static Web Apps serves a plain Vite build with no server-side rendering.
export default defineConfig({
  plugins: [react(), tailwindcss()],
});
