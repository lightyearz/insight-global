// ESLint flat config (ESLint 10 + eslint-config-next 16 native flat configs).
// eslint-plugin-react 7.x calls a removed ESLint API during React version
// auto-detection, so the version is pinned in settings.
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    settings: { react: { version: "19.3" } },
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      "react/no-array-index-key": "error",
      "react/jsx-no-target-blank": "error",
      "react-hooks/exhaustive-deps": "error",
      "react-hooks/set-state-in-effect": "error",
      "react-hooks/purity": "error",
      "react-hooks/immutability": "error",
      "no-console": ["error", { allow: ["warn", "error"] }],
      "prefer-const": "error",
    },
  },
  {
    files: ["scripts/**/*.mjs"],
    rules: { "no-console": "off" },
  },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts", "playwright-report/**", "test-results/**"]),
]);
