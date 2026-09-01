import { useState } from "react";

function App() {
  const [status, setStatus] = useState("Not checked");

  const checkBackend = async () => {
    try {
      const res = await fetch("/api/health"); // adjust to match your FastAPI route
      setStatus(res.ok ? "Backend reachable ✅" : `Error: ${res.status}`);
    } catch (err) {
      setStatus(`Failed to reach backend: ${err.message}`);
    }
  };

  return (
    <div style={{ padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>THREATZONE</h1>
      <p>Physics-Based Industrial Emergency Response Decision Support</p>
      <button onClick={checkBackend}>Check backend connection</button>
      <p>{status}</p>
    </div>
  );
}

export default App;
