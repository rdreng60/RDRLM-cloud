import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RDR Clinical Knowledge Base",
  description:
    "Ripple-down rules for clinical sessions — every rule readable, every rule correctable.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
