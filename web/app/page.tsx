"use client";

import { useEffect, useState } from "react";

type Health = { status: string; postgres: string; redis: string };

const API_URL = process.env.NEXT_PUBLIC_API_URL;

function Badge({ label, state }: { label: string; state: string }) {
  const ok = state === "ok";
  return (
    <div
      className={`rounded-full px-4 py-2 text-sm font-medium text-white ${
        ok ? "bg-green-600" : "bg-red-600"
      }`}
    >
      {label}: {state}
    </div>
  );
}

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((res) => res.json())
      .then(setHealth)
      .catch(() => setError(true));
  }, []);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4">
      <h1 className="text-2xl font-semibold">Platform status</h1>
      {error ? (
        <Badge label="API" state="unreachable" />
      ) : !health ? (
        <p>Loading...</p>
      ) : (
        <div className="flex gap-3">
          <Badge label="API" state="ok" />
          <Badge label="Postgres" state={health.postgres} />
          <Badge label="Redis" state={health.redis} />
        </div>
      )}
    </main>
  );
}