import "./style.css";
import "./schedule.css";
import "./capture.css";
import type { Viewport } from "next";

export const metadata = {
  title: "LifePilot",
  description: "Dein persönliches digitales Gedächtnis",
  applicationName: "LifePilot",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "LifePilot", statusBarStyle: "default" },
  icons: { icon: "/icon.svg", apple: "/icon-192.png" },
};

export const viewport: Viewport = { themeColor: "#f5f4ef" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="de"><body>{children}</body></html>;
}
