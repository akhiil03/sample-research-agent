import type { Metadata } from "next";
import "./globals.css";

const basePath = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");

export const metadata: Metadata = {
  title: "Research Agent · sample-research-agent",
  description:
    "An autonomous research agent built with LangGraph and FastAPI — it plans, searches, critiques itself, and writes cited reports you can watch live.",
  icons: {
    icon: [
      { url: `${basePath}/favicon.ico`, sizes: "any" },
      { url: `${basePath}/icon.svg`, type: "image/svg+xml" },
    ],
    apple: [{ url: `${basePath}/apple-icon.png`, sizes: "180x180" }],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
