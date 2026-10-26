"use client";

import { useEffect } from "react";

declare global {
  interface Window {
    Telegram?: { WebApp?: { ready: () => void } };
  }
}

// Tells Telegram the Mini App is ready. In a regular browser window.Telegram.WebApp is absent
// or has no initData, and this is a no-op.
export function TelegramReady() {
  useEffect(() => {
    window.Telegram?.WebApp?.ready();
  }, []);
  return null;
}
