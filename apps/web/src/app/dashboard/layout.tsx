"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Layers, Receipt, Search, Wallet, LogOut } from "lucide-react";
import { useRequireAuth, useAuth } from "@/lib/auth";

const NAV = [
  { href: "/dashboard", label: "Ledger", icon: Receipt },
  { href: "/dashboard/customers", label: "Customer lookup", icon: Search },
  { href: "/dashboard/budget", label: "Budget", icon: Wallet },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { token, loading } = useRequireAuth();
  const { logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  if (loading || !token) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  const activeLabel = NAV.find((item) => item.href === pathname)?.label ?? "Ledger";

  return (
    <div className="flex flex-1">
      <aside className="flex w-64 shrink-0 flex-col border-r border-border bg-surface">
        <div className="flex items-center gap-2.5 border-b border-border px-5 py-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 shadow-lg shadow-indigo-950/40">
            <Layers className="h-4.5 w-4.5 text-white" strokeWidth={2} />
          </div>
          <div>
            <h1 className="text-sm font-semibold leading-none text-foreground">Cost Ledger</h1>
            <p className="mt-1 text-[11px] leading-none text-muted-foreground">AI FinOps</p>
          </div>
        </div>

        <nav className="flex-1 space-y-0.5 px-3 py-4">
          {NAV.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition ${
                  active
                    ? "bg-accent-soft text-accent-hover"
                    : "text-muted hover:bg-surface-raised hover:text-foreground"
                }`}
              >
                <Icon className="h-4 w-4" strokeWidth={2} />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-border px-3 py-4">
          <button
            onClick={() => {
              logout();
              router.replace("/login");
            }}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-muted transition hover:bg-surface-raised hover:text-foreground"
          >
            <LogOut className="h-4 w-4" strokeWidth={2} />
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border bg-surface/60 px-8 py-4 backdrop-blur-sm">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-foreground">{activeLabel}</span>
          </div>
          <div className="flex items-center gap-2 rounded-full border border-border bg-background/60 px-3 py-1 text-xs text-muted-foreground">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px_theme(colors.emerald.400)]" />
            Live
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-8 py-8">{children}</main>
      </div>
    </div>
  );
}
