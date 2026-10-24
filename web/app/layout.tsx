import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Research Agent · sample-research-agent",
  description:
    "An autonomous research agent built with LangGraph and FastAPI — it plans, searches, critiques itself, and writes cited reports you can watch live.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
