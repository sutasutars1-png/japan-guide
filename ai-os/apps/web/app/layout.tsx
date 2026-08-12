import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI-OS · Execution Plane",
  description:
    "Local-first AI execution platform — a safe control plane for agents that write and run code.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
