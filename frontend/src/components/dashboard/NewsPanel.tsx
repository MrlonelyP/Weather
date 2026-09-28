import { Newspaper } from "lucide-react";
import { EmptyState, LoadingRows } from "@/components/ui/EmptyState";
import { Panel } from "@/components/ui/Panel";
import type { NewsResponse } from "@/types/news";
import { fmtDayTime } from "@/utils/format";

/** News and situation reports - kept visually separate from official warnings. */
export function NewsPanel({ data }: { data: NewsResponse | null }) {
  return (
    <Panel title="ข่าวสารและสถานการณ์ (ไม่ใช่ประกาศทางการ)" icon={Newspaper}>
      {!data ? <LoadingRows rows={3} /> : !data.available || data.items.length === 0 ? (
        <EmptyState icon={Newspaper} title="ยังไม่มีแหล่งข่าวที่เชื่อมต่อ" detail={data.reason ?? null} />
      ) : (
        <ul className="divide-y divide-line">
          {data.items.map((n) => (
            <li key={n.id} className="flex gap-3 px-4 py-3">
              {n.thumbnail_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={n.thumbnail_url} alt="" className="h-14 w-20 shrink-0 rounded-md object-cover" />
              )}
              <div className="min-w-0">
                <a href={n.url ?? undefined} target="_blank" rel="noopener noreferrer" className="line-clamp-2 text-[13px] text-ink hover:underline">{n.headline}</a>
                <p className="text-[11.5px] text-muted">{fmtDayTime(n.published_at)} · {n.source}</p>
                <p className="mt-1 flex flex-wrap gap-1">
                  {n.tags.map((t) => <span key={t} className="rounded bg-bg-2 px-1.5 text-[10.5px] text-ink-2">{t}</span>)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
