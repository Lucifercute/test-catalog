import type { Metadata } from "next";
import Script from "next/script";
import type { ReactNode } from "react";

import { TelegramReady } from "./telegram-ready";

export const metadata: Metadata = {
  title: "Каталог",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      {/* Telegram's script sets --tg-theme-* on <html>; fallbacks are for a regular browser. */}
      <body
        style={{
          backgroundColor: "var(--tg-theme-bg-color, #fff)",
          color: "var(--tg-theme-text-color, #000)",
        }}
      >
        {/* Telegram Mini App SDK; must load before the app hydrates. Harmless in a browser. */}
        <Script src="https://telegram.org/js/telegram-web-app.js" strategy="beforeInteractive" />
        <TelegramReady />
        {children}
      </body>
    </html>
  );
}
