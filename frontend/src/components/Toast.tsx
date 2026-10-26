import { clsx } from "clsx";
import { X } from "lucide-react";
import { useEffect, useState } from "react";

type Toast = { id: number; message: string; tone: "info" | "error" };
type Listener = (toast: Toast) => void;

const listeners = new Set<Listener>();
let nextId = 1;

/** Shows a short message at the bottom of the screen. Safe to call from anywhere, including outside React. */
export function notify(message: string, tone: Toast["tone"] = "info"): void {
  const toast = { id: nextId++, message, tone };
  listeners.forEach((listen) => listen(toast));
}

const SHOW_MS = 5000;

export function ToastHost() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  useEffect(() => {
    const listen: Listener = (toast) => {
      setToasts((all) => [...all.slice(-2), toast]);
      window.setTimeout(() => setToasts((all) => all.filter((t) => t.id !== toast.id)), SHOW_MS);
    };
    listeners.add(listen);
    return () => {
      listeners.delete(listen);
    };
  }, []);
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role={t.tone === "error" ? "alert" : "status"}
          className={clsx(
            "pointer-events-auto flex max-w-md items-center gap-3 rounded-xl px-4 py-3 text-sm shadow-lg",
            t.tone === "error" ? "bg-bad text-white" : "bg-ink text-white",
          )}
        >
          <span>{t.message}</span>
          <button
            type="button"
            aria-label="Dismiss"
            className="rounded p-1 hover:bg-white/10"
            onClick={() => setToasts((all) => all.filter((x) => x.id !== t.id))}
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  );
}
