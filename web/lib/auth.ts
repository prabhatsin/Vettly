"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearToken, getToken, setToken } from "./api";
import type { Role, User } from "./types";

export async function login(email: string, password: string): Promise<User> {
  const res = await api<{ access_token: string }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setToken(res.access_token);
  return api<User>("/auth/me");
}

export const homeFor = (role: Role) => (role === "employer" ? "/employer" : "/jobs");

export function useUser(requiredRole?: Role) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api<User>("/auth/me")
      .then((u) => {
        if (requiredRole && u.role !== requiredRole) router.replace(homeFor(u.role));
        else setUser(u);
      })
      .catch(() => {
        clearToken();
        router.replace("/login");
      });
  }, [router, requiredRole]);

  return user;
}