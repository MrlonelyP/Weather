import type { GeoJSONSource, Map as MlMap } from "maplibre-gl";

export const EMPTY_FC: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

/** true while the map (and its style) is still alive */
export function alive(map: MlMap): boolean {
  try {
    return !!map.getStyle();
  } catch {
    return false;
  }
}

export function ensureSource(map: MlMap, id: string, data: GeoJSON.FeatureCollection = EMPTY_FC) {
  if (!map.getSource(id)) map.addSource(id, { type: "geojson", data });
}

export function setData(map: MlMap, id: string, data: GeoJSON.FeatureCollection) {
  if (!alive(map)) return;
  (map.getSource(id) as GeoJSONSource | undefined)?.setData(data);
}

export function setVisible(map: MlMap, layerIds: string[], visible: boolean) {
  if (!alive(map)) return;
  for (const id of layerIds) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
  }
}

export function removeAll(map: MlMap, layerIds: string[], sourceId: string) {
  if (!alive(map)) return;
  for (const id of layerIds) if (map.getLayer(id)) map.removeLayer(id);
  if (map.getSource(sourceId)) map.removeSource(sourceId);
}

export function pointsFC<T extends { lat: number | null; lon: number | null }>(
  items: T[],
  props: (item: T) => Record<string, string | number | boolean | null>,
): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: items
      .filter((i) => i.lat !== null && i.lon !== null)
      .map((i) => ({ type: "Feature", geometry: { type: "Point", coordinates: [i.lon as number, i.lat as number] }, properties: props(i) })),
  };
}
