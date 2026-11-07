import type { Metadata } from "next";
import { Suspense } from "react";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { LiveProvider } from "@/lib/live";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

const geistSans = Geist({ variable: "--font-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "PODSYU",
  description: "Local AI content factory: podcast clips, creator clips and story shorts",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`dark ${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full bg-background">
        <LiveProvider>
          <TooltipProvider>
            <div className="flex flex-col md:flex-row min-h-screen">
              <Suspense fallback={<div className="hidden md:block w-64 shrink-0 bg-sidebar" />}>
                <Sidebar />
              </Suspense>
              <main className="flex-1 min-w-0 glow">
                <div className="mx-auto max-w-7xl px-4 md:px-8 py-6 md:py-8">{children}</div>
              </main>
            </div>
            <Toaster richColors position="bottom-right" />
          </TooltipProvider>
        </LiveProvider>
      </body>
    </html>
  );
}
