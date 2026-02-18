import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DailyLens | News Discovery",
  description: "Adaptive personalized article discovery",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
