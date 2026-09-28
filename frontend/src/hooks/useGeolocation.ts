"use client";

import { useCallback, useState } from "react";

export interface GeoState {
  position: { lat: number; lon: number } | null;
  error: string | null;
  locating: boolean;
  locate: () => void;
  clear: () => void;
}

/** Optional feature: the dashboard works fully without the user's location. */
export function useGeolocation(): GeoState {
  const [position, setPosition] = useState<{ lat: number; lon: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);

  const locate = useCallback(() => {
    if (!("geolocation" in navigator)) {
      setError("เบราว์เซอร์นี้ไม่รองรับการระบุตำแหน่ง");
      return;
    }
    setLocating(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setPosition({ lat: pos.coords.latitude, lon: pos.coords.longitude });
        setLocating(false);
      },
      (err) => {
        setError(err.code === err.PERMISSION_DENIED ? "ไม่ได้รับอนุญาตให้ใช้ตำแหน่ง" : "ระบุตำแหน่งไม่สำเร็จ");
        setLocating(false);
      },
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 300_000 },
    );
  }, []);

  return { position, error, locating, locate, clear: () => setPosition(null) };
}
