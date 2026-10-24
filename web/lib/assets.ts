const basePath = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");

export function asset(path: string): string {
  return `${basePath}${path}`;
}
