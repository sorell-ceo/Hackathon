import { useEffect, useState } from "react";
import { API_BASE_URL } from "./config.js";
import HazardMap from "./HazardMap.jsx";

const FALLBACK_FUEL_TYPES = [
  "gasoline",
  "diesel",
  "crude_oil",
  "lpg_propane",
  "lng_methane",
  "jet_fuel",
];

const EMPTY_FACILITY = (id) => ({
  facility_id: id,
  latitude: "",
  longitude: "",
  tank: { diameter_m: "", height_m: "", volume_m3: "", fill_fraction: 0.9 },
  wind: { speed_m_s: "", direction_deg: 0 },
  fuel_type: "gasoline",
  release_fraction: 0.15,
});

function toNumber(v) {
  return v === "" ? undefined : Number(v);
}

function buildPayload(f) {
  return {
    facility_id: f.facility_id,
    latitude: toNumber(f.latitude),
    longitude: toNumber(f.longitude),
    tank: {
      diameter_m: toNumber(f.tank.diameter_m),
      height_m: toNumber(f.tank.height_m),
      volume_m3: toNumber(f.tank.volume_m3),
      fill_fraction: toNumber(f.tank.fill_fraction),
    },
    wind: {
      speed_m_s: toNumber(f.wind.speed_m_s),
      direction_deg: toNumber(f.wind.direction_deg),
    },
    fuel_type: f.fuel_type,
    release_fraction: toNumber(f.release_fraction),
  };
}

function FacilityForm({ label, accent, value, onChange }) {
  const set = (path, val) => {
    const next = structuredClone(value);
    let obj = next;
    const keys = path.split(".");
    for (let i = 0; i < keys.length - 1; i++) obj = obj[keys[i]];
    obj[keys[keys.length - 1]] = val;
    onChange(next);
  };

  return (
    <fieldset className="facility-panel" style={{ "--accent": accent }}>
      <legend>{label}</legend>

      <label className="field">
        <span>Facility ID</span>
        <input
          value={value.facility_id}
          onChange={(e) => set("facility_id", e.target.value)}
        />
      </label>

      <div className="field-row">
        <label className="field">
          <span>Latitude</span>
          <input
            type="number"
            step="any"
            value={value.latitude}
            onChange={(e) => set("latitude", e.target.value)}
          />
        </label>
        <label className="field">
          <span>Longitude</span>
          <input
            type="number"
            step="any"
            value={value.longitude}
            onChange={(e) => set("longitude", e.target.value)}
          />
        </label>
      </div>

      <p className="group-label">Tank geometry</p>
      <div className="field-row">
        <label className="field">
          <span>Diameter (m)</span>
          <input
            type="number"
            step="any"
            min="0"
            value={value.tank.diameter_m}
            onChange={(e) => set("tank.diameter_m", e.target.value)}
          />
        </label>
        <label className="field">
          <span>Height (m)</span>
          <input
            type="number"
            step="any"
            min="0"
            value={value.tank.height_m}
            onChange={(e) => set("tank.height_m", e.target.value)}
          />
        </label>
      </div>
      <div className="field-row">
        <label className="field">
          <span>Volume (m³)</span>
          <input
            type="number"
            step="any"
            min="0"
            value={value.tank.volume_m3}
            onChange={(e) => set("tank.volume_m3", e.target.value)}
          />
        </label>
        <label className="field">
          <span>Fill fraction</span>
          <input
            type="number"
            step="0.01"
            min="0.01"
            max="1"
            value={value.tank.fill_fraction}
            onChange={(e) => set("tank.fill_fraction", e.target.value)}
          />
        </label>
      </div>

      <p className="group-label">Wind</p>
      <div className="field-row">
        <label className="field">
          <span>Speed (m/s)</span>
          <input
            type="number"
            step="any"
            min="0"
            value={value.wind.speed_m_s}
            onChange={(e) => set("wind.speed_m_s", e.target.value)}
          />
        </label>
        <label className="field">
          <span>Direction (° from)</span>
          <input
            type="number"
            step="any"
            min="0"
            max="359"
            value={value.wind.direction_deg}
            onChange={(e) => set("wind.direction_deg", e.target.value)}
          />
        </label>
      </div>

      <p className="group-label">Fuel</p>
      <div className="field-row">
        <label className="field">
          <span>Fuel type</span>
          <select
            value={value.fuel_type}
            onChange={(e) => set("fuel_type", e.target.value)}
          >
            {FALLBACK_FUEL_TYPES.map((ft) => (
              <option key={ft} value={ft}>
                {ft.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Release fraction</span>
          <input
            type="number"
            step="0.01"
            min="0.01"
            max="1"
            value={value.release_fraction}
            onChange={(e) => set("release_fraction", e.target.value)}
          />
        </label>
      </div>
    </fieldset>
  );
}

function SummaryGrid({ data }) {
  if (!data || typeof data !== "object") return null;
  return (
    <dl className="summary-grid">
      {Object.entries(data).map(([k, v]) => (
        <div className="summary-row" key={k}>
          <dt>{k.replace(/_/g, " ")}</dt>
          <dd>{typeof v === "number" ? v.toLocaleString() : String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function ComparisonTable({ rows }) {
  if (!rows || rows.length === 0) return null;
  const cols = Object.keys(rows[0]);
  return (
    <table className="comparison-table">
      <thead>
        <tr>
          {cols.map((c) => (
            <th key={c}>{c.replace(/_/g, " ")}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i}>
            {cols.map((c) => (
              <td key={c}>
                {typeof row[c] === "number" ? row[c].toLocaleString() : row[c]}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function App() {
  const [facilityA, setFacilityA] = useState(EMPTY_FACILITY("FAC-A"));
  const [facilityB, setFacilityB] = useState(EMPTY_FACILITY("FAC-B"));
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [apiUp, setApiUp] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/health`)
      .then((r) => setApiUp(r.ok))
      .catch(() => setApiUp(false));
  }, []);

  const runCompare = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API_BASE_URL}/api/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          facility_a: buildPayload(facilityA),
          facility_b: buildPayload(facilityB),
        }),
      });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(body.detail || "Request failed");
      }
      setResult(body);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const comparisonKeys = result
    ? Object.keys(result).filter((k) => k.endsWith("_comparison_m"))
    : [];

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-text">
          <h1>THREATZONE</h1>
          <p>Physics-based industrial emergency response decision support</p>
        </div>
        <div className={`status ${apiUp ? "up" : apiUp === false ? "down" : ""}`}>
          <span className="status-dot" />
          {apiUp === null ? "checking backend…" : apiUp ? "backend online" : "backend unreachable"}
        </div>
      </header>

      <main className="panels">
        <FacilityForm
          label="Facility A"
          accent="#ff6b35"
          value={facilityA}
          onChange={setFacilityA}
        />
        <FacilityForm
          label="Facility B"
          accent="#4fd1c5"
          value={facilityB}
          onChange={setFacilityB}
        />
      </main>

      <div className="actions">
        <button onClick={runCompare} disabled={loading}>
          {loading ? "Calculating…" : "Compare hazard zones"}
        </button>
      </div>

      {error && (
        <div className="error-banner">
          <strong>Calculation failed.</strong> {error}
        </div>
      )}

      {result && (
        <section className="results">
          <HazardMap facilityA={facilityA} facilityB={facilityB} result={result} />

          <div className="results-summaries">
            <div>
              <h2 style={{ color: "#ff6b35" }}>Facility A</h2>
              <SummaryGrid data={result.facility_a} />
            </div>
            <div>
              <h2 style={{ color: "#4fd1c5" }}>Facility B</h2>
              <SummaryGrid data={result.facility_b} />
            </div>
          </div>

          {comparisonKeys.map((key) => (
            <div key={key} className="comparison-block">
              <h3>{key.replace(/_/g, " ")}</h3>
              <ComparisonTable rows={result[key]} />
            </div>
          ))}

          {result.explanation && (
            <p className="explanation">{result.explanation}</p>
          )}
        </section>
      )}
    </div>
  );
}
