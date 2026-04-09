import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** True when running on macOS (uses Cmd instead of Ctrl). */
export const isMac: boolean =
  typeof navigator !== "undefined" && navigator.platform.toUpperCase().includes("MAC");

/** Check if the platform modifier key is pressed (Cmd on macOS, Ctrl elsewhere). */
export function isModKey(e: KeyboardEvent | React.KeyboardEvent): boolean {
  return isMac ? e.metaKey : e.ctrlKey;
}

/** Display string for the platform modifier key ("⌘" on macOS, "Ctrl+" elsewhere). */
export const modKeyLabel: string = isMac ? "\u2318" : "Ctrl+";
