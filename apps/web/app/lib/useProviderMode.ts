"use client";

import { useEffect, useState } from "react";
import { api } from "./api";

export type ProviderMode = "mock" | "elevenlabs" | "unavailable";

export function useProviderMode(): ProviderMode {
  const [mode, setMode] = useState<ProviderMode>("unavailable");

  useEffect(() => {
    let active = true;
    const refresh = () => {
      void api<{ provider_mode?: string }>("/health")
        .then((health) => {
          if (active) {
            setMode(health.provider_mode === "elevenlabs" ? "elevenlabs" : "mock");
          }
        })
        .catch(() => {
          if (active) setMode("unavailable");
        });
    };
    refresh();
    const timer = window.setInterval(refresh, 10000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return mode;
}
