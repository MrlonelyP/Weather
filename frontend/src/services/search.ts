import type { SearchResponse } from "@/types/search";
import { apiGet } from "./api";

export const searchService = {
  query: (q: string, signal?: AbortSignal) => apiGet<SearchResponse>("/api/search", { q }, signal),
};
