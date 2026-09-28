import { Drawer } from "@/components/ui/Drawer";
import { REFRESH_MS } from "@/config/app";

export function SettingsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Drawer open={open} onClose={onClose} width={440} title={<p className="font-[family-name:var(--font-display)] text-[16px] font-semibold">เกี่ยวกับข้อมูลบนหน้านี้</p>}>
      <div className="space-y-3 p-5 text-[13px] leading-relaxed text-ink-2">
        <p>หน้าจอดึงข้อมูลจากระบบของเราทุก {Math.round(REFRESH_MS / 1000)} วินาที การรีเฟรชหน้าจอ<b>ไม่ได้</b>แปลว่าข้อมูลต้นทางใหม่ทุกครั้ง ให้ดูเวลาของข้อมูลและอายุข้อมูลที่แสดงในแต่ละส่วน</p>
        <p>ระบบของเราไปดึงข้อมูลจากหน่วยงานต้นทางตามรอบของแต่ละแหล่งเท่านั้น เว็บไซต์นี้ไม่เรียก API ภายนอกโดยตรง</p>
        <p>สถานะระดับน้ำ (ปกติ / เฝ้าระวัง / เสี่ยงสูง / วิกฤต) และการประเมินผลของฝนต่อระดับน้ำ เป็น<b>การประเมินโดยระบบ</b> ไม่ใช่ประกาศเตือนภัยหรือคำสั่งทางราชการ โปรดติดตามประกาศจากหน่วยงานที่เกี่ยวข้อง</p>
        <p className="text-muted">แหล่งข้อมูล: ThaiWater (สสน.), กรมอุตุนิยมวิทยา, กรมชลประทาน, Open-Meteo (ECMWF/GFS/JMA)</p>
      </div>
    </Drawer>
  );
}
