import type { ISODate } from "./common";

export type NewsTag = "weather" | "flood" | "dam" | "river" | "storm" | "official" | "news";

export interface NewsItem {
  id: string;
  headline: string;
  published_at: ISODate;
  source: string;
  url: string | null;
  thumbnail_url: string | null;
  tags: NewsTag[];
  official: boolean;
}

export interface NewsResponse {
  available: boolean;
  reason?: string;
  items: NewsItem[];
}
