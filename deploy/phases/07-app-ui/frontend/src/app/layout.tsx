import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NagarVault — Officer Console",
  description: "Air-gapped municipal intelligence console",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
