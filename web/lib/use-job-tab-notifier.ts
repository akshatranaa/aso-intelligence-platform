"use client";

/**
 * Reflects a background job's status in the browser tab: an animated favicon
 * while it runs, and a persistent checkmark/error favicon + title prefix once
 * it finishes IF the user has switched away — so they don't have to babysit
 * the tab. Everything reverts automatically the moment the tab regains focus.
 * Also fires a system notification on completion if permission was granted.
 */

import { useEffect, useRef } from "react";

type JobStatus = "running" | "done" | "error" | undefined;

export function useJobTabNotifier(status: JobStatus, label: string) {
  const original = useRef<{ title: string; href: string } | null>(null);

  useEffect(() => {
    const link = getOrCreateIconLink();
    if (!original.current) {
      original.current = { title: document.title, href: link.href };
    }
    const revert = () => {
      if (!original.current) return;
      document.title = original.current.title;
      link.href = original.current.href;
    };

    if (status === "running") {
      let angle = 0;
      const timer = setInterval(() => {
        angle = (angle + 30) % 360;
        link.href = spinnerIcon(angle);
      }, 150);
      return () => clearInterval(timer);
    }

    if (status === "done" || status === "error") {
      const away = document.hidden || !document.hasFocus();
      if (!away) {
        revert();
        return;
      }
      link.href = status === "done" ? checkIcon() : errorIcon();
      document.title = `${status === "done" ? "✅" : "⚠️"} ${label}`;
      notify(
        status === "done" ? "Collection complete" : "Collection failed",
        label
      );
      const onBack = () => {
        revert();
        window.removeEventListener("focus", onBack);
        document.removeEventListener("visibilitychange", onVisible);
      };
      const onVisible = () => {
        if (!document.hidden) onBack();
      };
      window.addEventListener("focus", onBack);
      document.addEventListener("visibilitychange", onVisible);
      return () => {
        window.removeEventListener("focus", onBack);
        document.removeEventListener("visibilitychange", onVisible);
      };
    }

    revert();
  }, [status, label]);
}

/** Ask for notification permission — call from a user-gesture handler. */
export function requestNotifyPermission() {
  try {
    if ("Notification" in window && Notification.permission === "default") {
      void Notification.requestPermission();
    }
  } catch {
    /* Notification API unavailable — ignore */
  }
}

function notify(title: string, body: string) {
  try {
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification(title, { body, silent: true });
    }
  } catch {
    /* ignore */
  }
}

function getOrCreateIconLink(): HTMLLinkElement {
  let link = document.querySelector<HTMLLinkElement>('link[rel~="icon"]');
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  return link;
}

function svgDataUrl(svg: string): string {
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function spinnerIcon(angleDeg: number): string {
  return svgDataUrl(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
      <circle cx="16" cy="16" r="13" fill="none" stroke="#e0e7ff" stroke-width="4"/>
      <path d="M16 3 a13 13 0 0 1 0 26" fill="none" stroke="#4f46e5" stroke-width="4"
            stroke-linecap="round" transform="rotate(${angleDeg} 16 16)"/>
    </svg>`
  );
}

function checkIcon(): string {
  return svgDataUrl(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
      <circle cx="16" cy="16" r="15" fill="#16a34a"/>
      <path d="M9 17l5 5 9-11" fill="none" stroke="white" stroke-width="3.5"
            stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`
  );
}

function errorIcon(): string {
  return svgDataUrl(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
      <circle cx="16" cy="16" r="15" fill="#dc2626"/>
      <path d="M11 11l10 10M21 11l-10 10" stroke="white" stroke-width="3.5"
            stroke-linecap="round"/>
    </svg>`
  );
}
