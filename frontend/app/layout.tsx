import type { Metadata } from "next";
import "@fontsource/manrope/400.css";
import "@fontsource/manrope/500.css";
import "@fontsource/manrope/600.css";
import "@fontsource/manrope/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import "@fontsource/ibm-plex-mono/700.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "ClearBuy — See Real Furniture in Your Exact Room",
  description:
    "Zero-measurement spatial commerce compiler with automatic room calibration, hard fit & budget verification, and live Shopify checkouts.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="bg-at-bg text-at-ink font-sans antialiased selection:bg-at-accent/25 selection:text-at-ink overflow-hidden">
        {children}
      </body>
    </html>
  );
}
