import type { NewsResponse } from "@/types/news";
import { apiGet } from "./api";

export const newsService = {
  list: (signal?: AbortSignal) => apiGet<NewsResponse>("/api/news", undefined, signal),
};
