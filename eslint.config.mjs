import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";

// Flat config for ESLint v9 + eslint-config-next (Next.js 16).
// Replaces the removed `next lint` command — run with: npm run lint
const eslintConfig = defineConfig([
  ...nextVitals,
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "node_modules/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
