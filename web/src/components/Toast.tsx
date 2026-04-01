/**
 * Toast adapter: wraps sonner's toast API to match our existing call sites.
 * All callers use positional args: toast.error(title, description).
 * Sonner uses options objects: toast.error(title, { description }).
 * This adapter bridges the two so we don't need to change 50+ callers.
 */
import { toast as sonnerToast } from "sonner";

type ToastType = "error" | "success" | "info" | "warning";

function toastByType(type: ToastType, title: string, opts: Record<string, unknown>) {
  switch (type) {
    case "error": return sonnerToast.error(title, opts);
    case "success": return sonnerToast.success(title, opts);
    case "info": return sonnerToast.info(title, opts);
    case "warning": return sonnerToast.warning(title, opts);
  }
}

function toast(type: ToastType, title: string, description?: string, duration = 5000) {
  return toastByType(type, title, { description, duration });
}

toast.error = (title: string, description?: string) =>
  sonnerToast.error(title, { description, duration: 7000 });

toast.success = (title: string, description?: string) =>
  sonnerToast.success(title, { description, duration: 3000 });

toast.info = (title: string, description?: string) =>
  sonnerToast.info(title, { description, duration: 4000 });

toast.warning = (title: string, description?: string) =>
  sonnerToast.warning(title, { description, duration: 5000 });

toast.persistent = (
  type: ToastType,
  title: string,
  description?: string,
  action?: { label: string; onClick: () => void },
) => {
  return toastByType(type, title, {
    description,
    duration: Infinity,
    action: action ? { label: action.label, onClick: action.onClick } : undefined,
  });
};

toast.dismiss = (id: string | number) => sonnerToast.dismiss(id);

export { toast };
export type { ToastType };
