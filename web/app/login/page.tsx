"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { homeFor, login } from "@/lib/auth";

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const user = await login(email, password);
      router.replace(homeFor(user.role));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <main className="mx-auto mt-20 max-w-sm p-4">
      <h1 className="mb-4 text-2xl font-semibold">Log in</h1>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <input className="rounded border p-2" type="email" placeholder="Email" required
          value={email} onChange={(e) => setEmail(e.target.value)} />
        <input className="rounded border p-2" type="password" placeholder="Password" required
          value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button className="rounded bg-black p-2 text-white">Log in</button>
      </form>
      <p className="mt-3 text-sm">
        New here? <Link className="underline" href="/register">Register</Link>
      </p>
    </main>
  );
}