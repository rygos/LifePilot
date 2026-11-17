import "./style.css";
import "./schedule.css";
import "./capture.css";

export const metadata = { title: "LifePilot", description: "Dein persönliches digitales Gedächtnis" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="de"><body>{children}</body></html>;
}
