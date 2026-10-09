import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ProofOfPost · RuleRegistry",
  description:
    "Stake-backed content-compliance registry settled by GenLayer validator consensus.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
