import { createContext, useContext, useState, useCallback } from "react";
import { cn } from "@/lib/utils";

interface Toast {
  id: string;
  type: "success" | "error";
  message: string;
}

interface ToastContextValue {
  success: string | null;
  error: string | null;
  showSuccess: (msg: string) => void;
  showError: (msg: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const remove = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (type: "success" | "error", message: string) => {
      const id = Math.random().toString(36).slice(2);
      setToasts((prev) => [...prev, { id, type, message }]);
      setTimeout(() => remove(id), type === "error" ? 5000 : 3000);
    },
    [remove]
  );

  const showSuccess = useCallback((msg: string) => show("success", msg), [show]);
  const showError = useCallback((msg: string) => show("error", msg), [show]);

  const success = toasts.find((t) => t.type === "success")?.message || null;
  const error = toasts.find((t) => t.type === "error")?.message || null;

  return (
    <ToastContext.Provider value={{ success, error, showSuccess, showError }}>
      {children}
      <div className="fixed top-14 right-4 z-[100] flex flex-col gap-2 pointer-events-none">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cn(
              "pointer-events-auto px-4 py-2 rounded-xl shadow-lg text-sm max-w-xs transition-all duration-200",
              t.type === "success" ? "bg-success text-white" : "bg-danger text-white"
            )}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
