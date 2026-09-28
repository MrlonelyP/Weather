/**
 * HTTP client for OUR backend only.
 *
 * All paths are relative (/api/...). In production Next.js rewrites them to the
 * FastAPI server (see next.config.ts), so the browser never talks to an
 * external weather API and no API key exists in the frontend.
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly path: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function buildPath(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

export async function apiGet<T>(path: string, query?: Query, signal?: AbortSignal): Promise<T> {
  const url = buildPath(path, query);
  let res: Response;
  try {
    res = await fetch(url, { signal, headers: { Accept: "application/json" }, cache: "no-store" });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, url, "ติดต่อระบบหลังบ้านไม่ได้");
  }
  if (!res.ok) {
    throw new ApiError(res.status, url, `API ${res.status}`);
  }
  return (await res.json()) as T;
}
