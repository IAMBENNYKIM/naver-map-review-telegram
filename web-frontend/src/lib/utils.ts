import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Tailwind 클래스명을 조건부로 합치고 충돌을 정리하는 헬퍼.
 * shadcn/ui 규약의 `cn` 유틸리티와 동일한 역할을 한다.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
