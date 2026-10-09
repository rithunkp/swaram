import type { Metadata } from "next";
import "./globals.css";
import "./workflow.css";
import "./dashboard.css";

export const metadata: Metadata = {
  title: "Swaram · Campaigns",
  description: "Multilingual calling campaigns, made simple.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
