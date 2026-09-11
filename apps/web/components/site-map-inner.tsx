"use client";

import { useEffect } from "react";
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Polyline,
  Popup,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import type { GISPayload, GeoJSONGeometry } from "@/lib/types";
import "leaflet/dist/leaflet.css";

// Keyless dark basemap. (CARTO's dark_all tiles now require an API key and
// serve an "API KEY REQUIRED" watermark without one.) Override with
// NEXT_PUBLIC_TILE_URL to use another provider.
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas";
const TILE_URL =
  process.env.NEXT_PUBLIC_TILE_URL || `${ESRI}/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`;
const LABEL_URL = process.env.NEXT_PUBLIC_TILE_URL
  ? null
  : `${ESRI}/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`;
const TILE_ATTR =
  'Tiles &copy; <a href="https://www.esri.com">Esri</a> &mdash; Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

export interface SiteMapProps {
  center: [number, number];
  zoom?: number;
  marker?: [number, number] | null;
  onPick?: (lat: number, lon: number) => void;
  gis?: GISPayload | null;
  altRoute?: GeoJSONGeometry | null;
  interactive?: boolean;
  className?: string;
}

function ClickHandler({ onPick }: { onPick: (lat: number, lon: number) => void }) {
  useMapEvents({
    click(e) {
      // Wrap so a click on a panned-around world copy stays within ±180°.
      const { lat, lng } = e.latlng.wrap();
      onPick(lat, lng);
    },
  });
  return null;
}

function FlyTo({ target, zoom }: { target: [number, number]; zoom: number }) {
  const map = useMap();
  useEffect(() => {
    map.flyTo(target, zoom, { duration: 1.2 });
  }, [map, target[0], target[1], zoom]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

function lineCoords(geometry: GeoJSONGeometry): [number, number][] {
  return (geometry.coordinates as [number, number][]).map(([lon, lat]) => [lat, lon]);
}

export default function SiteMapInner({
  center,
  zoom = 13,
  marker,
  onPick,
  gis,
  altRoute,
  interactive = true,
  className,
}: SiteMapProps) {
  return (
    <MapContainer
      center={center}
      zoom={zoom}
      className={className ?? "h-full w-full"}
      scrollWheelZoom={interactive}
      dragging={interactive}
      zoomControl={interactive}
      attributionControl
    >
      <TileLayer url={TILE_URL} attribution={TILE_ATTR} maxNativeZoom={16} maxZoom={19} />
      {LABEL_URL && <TileLayer url={LABEL_URL} maxNativeZoom={16} maxZoom={19} />}
      {onPick && <ClickHandler onPick={onPick} />}
      {marker && <FlyTo target={marker} zoom={Math.max(zoom, 13)} />}

      {marker && (
        <>
          <CircleMarker
            center={marker}
            radius={16}
            pathOptions={{ color: "#35C78F", weight: 1, fillOpacity: 0.08, opacity: 0.5 }}
          />
          <CircleMarker
            center={marker}
            radius={6}
            pathOptions={{ color: "#35C78F", weight: 2, fillColor: "#35C78F", fillOpacity: 0.9 }}
          >
            <Popup>Proposed site centroid</Popup>
          </CircleMarker>
        </>
      )}

      {gis && (
        <>
          <GeoJSON
            key={`fp-${gis.site.lat}`}
            data={gis.site.footprint as GeoJSON.GeoJsonObject}
            style={{ color: "#35C78F", weight: 1.5, dashArray: "6 4", fillOpacity: 0.05 }}
          />
          {gis.wetlands.map((w) => (
            <GeoJSON
              key={w.id}
              data={w.geometry as GeoJSON.GeoJsonObject}
              style={{
                color: w.state_protected ? "#F0625D" : "#E8B25A",
                weight: 1.5,
                fillOpacity: w.state_protected ? 0.28 : 0.18,
              }}
            >
              <Popup>
                <strong>{w.name}</strong>
                <br />
                {w.wetland_type} ({w.classification})
                <br />
                {w.distance_m.toFixed(0)} m {w.bearing} · {w.area_acres} ac
                {w.state_protected && (
                  <>
                    <br />
                    <span style={{ color: "#F0625D" }}>{w.state_class}</span>
                  </>
                )}
                <br />
                <em>{w.source}</em>
              </Popup>
            </GeoJSON>
          ))}
          {gis.habitats
            .filter((h) => h.geometry && (h.geometry.coordinates as unknown[])?.length)
            .map((h) => (
              <GeoJSON
                key={h.id}
                data={h.geometry as GeoJSON.GeoJsonObject}
                style={{ color: "#E8B25A", weight: 1.5, dashArray: "4 4", fillOpacity: 0.14 }}
              >
                <Popup>
                  <strong>{h.common_name}</strong> <em>({h.species})</em>
                  <br />
                  {h.status} — {h.unit_name}
                  {h.distance_m != null && (
                    <>
                      <br />
                      {(h.distance_m / 1000).toFixed(1)} km {h.bearing}
                    </>
                  )}
                  <br />
                  <em>{h.source}</em>
                </Popup>
              </GeoJSON>
            ))}
          {gis.protected_lands.map((p) => (
            <GeoJSON
              key={p.id}
              data={p.geometry as GeoJSON.GeoJsonObject}
              style={{ color: "#5CA8FF", weight: 1, fillOpacity: 0.08 }}
            >
              <Popup>
                <strong>{p.name}</strong>
                <br />
                {p.designation} · {p.manager}
                {p.gap_status && <> · GAP {p.gap_status}</>}
                <br />
                {p.overlaps_footprint
                  ? "Overlaps the project footprint"
                  : `${(p.distance_m / 1000).toFixed(1)} km ${p.bearing}`}
              </Popup>
            </GeoJSON>
          ))}
          {gis.flood_zones.map((f) => (
            <GeoJSON
              key={f.id}
              data={f.geometry as GeoJSON.GeoJsonObject}
              style={{ color: "#7DD3FC", weight: 1, dashArray: "2 4", fillOpacity: 0.1 }}
            >
              <Popup>
                <strong>FEMA Zone {f.zone}</strong>
                {f.sfha && <> · base floodplain</>}
                <br />
                {f.description}
              </Popup>
            </GeoJSON>
          ))}
        </>
      )}

      {altRoute && (
        <Polyline
          positions={lineCoords(altRoute)}
          pathOptions={{ color: "#35C78F", weight: 3, dashArray: "8 6", opacity: 0.9 }}
        >
          <Popup>Alternative routing corridor</Popup>
        </Polyline>
      )}
    </MapContainer>
  );
}
