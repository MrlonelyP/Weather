import type { WarningsResponse } from "@/types/warning";
import { apiGet } from "./api";

export const warningService = {
  list: (signal?: AbortSignal) => apiGet<WarningsResponse>("/api/warnings", { hours: 48 }, signal),
};
