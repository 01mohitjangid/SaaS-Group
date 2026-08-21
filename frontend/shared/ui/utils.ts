import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn's `cn`: compose conditional classes, then let the last Tailwind class win. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
