import { defineConfig } from "allure";

export default defineConfig({
  name: "Agentic-QA API",
  historyPath:
    process.env.AGENTIC_QA_ALLURE_HISTORY_PATH ??
    "./.runtime/allure-history.jsonl",
  plugins: {
    awesome: {
      options: {
        reportName: "Agentic-QA API",
        defaultSortBy: "status,asc",
      },
    },
  },
});
