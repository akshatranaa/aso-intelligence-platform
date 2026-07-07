import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Suspense } from "react";
import "./globals.css";
import { Providers } from "@/components/providers";
import { Sidebar, Topbar } from "@/components/shell";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "ASO Intelligence Platform",
  description: "App Store Optimization powered by AI",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full font-sans">
        <Providers>
          <div className="flex min-h-screen">
            {/* Sidebar/Topbar read the URL (useSearchParams) — needs Suspense */}
            <Suspense>
              <Sidebar />
            </Suspense>
            <div className="flex min-w-0 flex-1 flex-col">
              <Suspense>
                <Topbar />
              </Suspense>
              <main className="flex-1 px-8 py-6">{children}</main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
