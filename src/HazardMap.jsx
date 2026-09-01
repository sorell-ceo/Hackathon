import { useEffect, useMemo } from "react";
import {
  MapContainer,
  TileLayer,
  Circle,
  Marker,
  Popup,
  GeoJSON,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Vite doesn't resolve Leaflet's default marker image paths automatically —
// point them at a CDN instead of shipping broken icons.
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png",
  iconUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png",
  shadowUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
});

// Severity opacity ramp: level 1 is the smallest/most severe radius in every
// sample response we've seen (highest thermal threshold, closest to source),
// so it gets drawn last (on top) and most saturated. Later levels are larger,
// less severe, lower opacity, drawn first (underneath).
const LEVEL_STYLE = {
  1: { fillOpacity: 0.45, opacity: 0.9 },
  2: { fillOpacity: 0.28, opacity: 0.7 },
  3: { fillOpacity: 0.15, opacity: 0.5 },
};
const DEFAULT_STYLE = { fillOpacity: 0.15, opacity: 0.5 };

// Recursively search an object for anything that looks like a GeoJSON
// Polygon/MultiPolygon, in case the backend does return real hazard-zone
// geometry rather than just the radius comparison table. Falls back to
// nothing found, so the caller can draw circles from the known distances
// instead.
function findGeoJsonPolygons(obj, found = []) {
  if (!obj || typeof obj !== "object") return found;
  if (
    obj.type &&
    (obj.type === "Polygon" || obj.type === "MultiPolygon" || obj.type === "Feature")
  ) {
    found.push(obj);
    return found;
  }
  for (const v of Object.values(obj)) {
    if (v && typeof v === "object") findGeoJsonPolygons(v, found);
  }
  return found;
}

function FitBounds({ positions }) {
  const map = useMap();
  useEffect(() => {
    const valid = positions.filter(
      (p) => Number.isFinite(p[0]) && Number.isFinite(p[1])
    );
    if (valid.length === 0) return;
    if (valid.length === 1) {
      map.setView(valid[0], 15);
    } else {
      map.fitBounds(valid, { padding: [40, 40] });
    }
  }, [JSON.stringify(positions)]);
  return null;
}

export default function HazardMap({ facilityA, facilityB, result }) {
  const posA = [Number(facilityA.latitude), Number(facilityA.longitude)];
  const posB = [Number(facilityB.latitude), Number(facilityB.longitude)];
  const hasA = Number.isFinite(posA[0]) && Number.isFinite(posA[1]);
  const hasB = Number.isFinite(posB[0]) && Number.isFinite(posB[1]);

  const polygons = useMemo(
    () => (result ? findGeoJsonPolygons(result) : []),
    [result]
  );

  const thermalRows = result?.thermal_distance_comparison_m || [];

  if (!hasA && !hasB) {
    return (
      <div className="map-placeholder">
        Enter latitude/longitude for at least one facility to see hazard
        zones on the map.
      </div>
    );
  }

  return (
    <div className="hazard-map-wrap">
      <MapContainer
        center={hasA ? posA : posB}
        zoom={14}
        scrollWheelZoom
        className="hazard-map"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds positions={[posA, posB]} />

        {polygons.length > 0 &&
          polygons.map((geom, i) => (
            <GeoJSON
              key={i}
              data={geom}
              style={{ color: "#ff6b35", weight: 1, fillOpacity: 0.25 }}
            />
          ))}

        {/* Fallback: draw hazard-radius circles from the comparison table
            when no real polygon geometry is present in the response. */}
        {polygons.length === 0 &&
          thermalRows
            .slice()
            .sort((a, b) => b.level - a.level) // largest radius first, underneath
            .map((row) => (
              <div key={row.level}>
                {hasA && Number.isFinite(row.facility_a_m) && (
                  <Circle
                    center={posA}
                    radius={row.facility_a_m}
                    pathOptions={{
                      color: "#ff6b35",
                      ...(LEVEL_STYLE[row.level] || DEFAULT_STYLE),
                    }}
                  >
                    <Popup>
                      Facility A — level {row.level}: {row.facility_a_m.toLocaleString()} m
                    </Popup>
                  </Circle>
                )}
                {hasB && Number.isFinite(row.facility_b_m) && (
                  <Circle
                    center={posB}
                    radius={row.facility_b_m}
                    pathOptions={{
                      color: "#4fd1c5",
                      ...(LEVEL_STYLE[row.level] || DEFAULT_STYLE),
                    }}
                  >
                    <Popup>
                      Facility B — level {row.level}: {row.facility_b_m.toLocaleString()} m
                    </Popup>
                  </Circle>
                )}
              </div>
            ))}

        {hasA && (
          <Marker position={posA}>
            <Popup>{facilityA.facility_id || "Facility A"}</Popup>
          </Marker>
        )}
        {hasB && (
          <Marker position={posB}>
            <Popup>{facilityB.facility_id || "Facility B"}</Popup>
          </Marker>
        )}
      </MapContainer>

      <div className="map-legend">
        <div>
          <span className="swatch" style={{ background: "#ff6b35" }} />
          Facility A hazard zones
        </div>
        <div>
          <span className="swatch" style={{ background: "#4fd1c5" }} />
          Facility B hazard zones
        </div>
        {polygons.length === 0 && (
          <p className="legend-note">
            Zones approximated as circles from thermal_distance_comparison_m
            (no polygon geometry found in the API response). Darker = closer
            / higher-severity threshold.
          </p>
        )}
      </div>
    </div>
  );
}
