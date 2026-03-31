import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle, Info, X, XCircle } from "lucide-react";

export type ToastType = "error" | "success" | "info" | "warning";

export interface ToastMessage {
  id: string;
  type: ToastType;
  title: string;
  description?: string;
  duration?: number;
}

/* ── Global toast state (lightweight, no extra deps) ──────────── */

type Listener = () => void;
let toasts: ToastMessage[] = [];
const listeners = new Set<Listener>();

function emit() {
  listeners.forEach((l) => l());
}

export function toast(
  type: ToastType,
  title: string,
  description?: string,
  duration = 5000,
) {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
  toasts = [...toasts, { id, type, title, description, duration }];
  emit();
}

toast.error = (title: string, description?: string) =>
  toast("error", title, description, 7000);
toast.success = (title: string, description?: string) =>
  toast("success", title, description, 3000);
toast.info = (title: string, description?: string) =>
  toast("info", title, description, 4000);
toast.warning = (title: string, description?: string) =>
  toast("warning", title, description, 5000);

function dismiss(id: string) {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

function useToasts(): ToastMessage[] {
  const [, setTick] = useState(0);
  useEffect(() => {
    const listener = () => setTick((t) => t + 1);
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }, []);
  return toasts;
}

/* ── Components ───────────────────────────────────────────────── */

const icons: Record<ToastType, typeof Info> = {
  error: XCircle,
  success: CheckCircle,
  info: Info,
  warning: AlertTriangle,
};

const styles: Record<ToastType, string> = {
  error: "border-red-500/40 bg-red-500/10 text-red-400",
  success: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
  info: "border-blue-500/40 bg-blue-500/10 text-blue-400",
  warning: "border-amber-500/40 bg-amber-500/10 text-amber-400",
};

function ToastItem({ t }: { t: ToastMessage }) {
  const [exiting, setExiting] = useState(false);
  const Icon = icons[t.type];

  useEffect(() => {
    if (!t.duration) return;
    const timer = setTimeout(() => setExiting(true), t.duration);
    return () => clearTimeout(timer);
  }, [t.duration]);

  useEffect(() => {
    if (!exiting) return;
    const timer = setTimeout(() => dismiss(t.id), 300);
    return () => clearTimeout(timer);
  }, [exiting, t.id]);

  return (
    <div
      className={`flex items-start gap-3 rounded-lg border px-4 py-3 shadow-lg backdrop-blur-sm transition-all duration-300 ${styles[t.type]} ${
        exiting ? "translate-x-[120%] opacity-0" : "translate-x-0 opacity-100"
      }`}
    >
      <Icon size={16} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-text-primary">{t.title}</p>
        {t.description && (
          <p className="mt-0.5 text-xs text-text-muted line-clamp-2">
            {t.description}
          </p>
        )}
      </div>
      <button
        onClick={() => setExiting(true)}
        className="shrink-0 text-text-muted hover:text-text-primary transition-colors"
      >
        <X size={14} />
      </button>
    </div>
  );
}

export function ToastContainer() {
  const items = useToasts();

  if (items.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col-reverse gap-2 w-80 max-w-[calc(100vw-2rem)]">
      {items.map((t) => (
        <ToastItem key={t.id} t={t} />
      ))}
    </div>
  );
}
