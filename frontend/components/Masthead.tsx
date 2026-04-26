"use client";

import Link from "next/link";
import { SeedlingMark } from "./Glyphs";

type NavItem = { href: string; label: string };

export function Masthead({ active = "home" }: { active?: "home" | "library" }) {
  const navItems: NavItem[] = [
    { href: "/#home", label: "Home" },
    { href: "/#create", label: "Create" },
    { href: "/#result", label: "Result" },
    { href: "/library", label: "Library" }
  ];
  const isActive = (href: string) =>
    (active === "library" && href === "/library") ||
    (active === "home" && href.startsWith("/#"));

  return (
    <header className="masthead reveal">
      <Link className="brand" href="/" aria-label="SeedEstate Field Studio">
        <span className="brand-mark">
          <SeedlingMark />
        </span>
        <span className="brand-text">
          <span className="brand-name">
            Seed<em>Estate</em>
          </span>
          <span className="brand-sub">Field Studio</span>
        </span>
      </Link>

      <nav className="nav" aria-label="Primary">
        {navItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={isActive(item.href) ? "is-active" : undefined}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      <span className="masthead-meta">Live · MMXXV</span>
    </header>
  );
}
