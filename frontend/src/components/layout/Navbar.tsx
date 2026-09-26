import { Link, useLocation } from 'react-router-dom';
import { Button } from '../ui/Button';
import { Logo } from '../ui/Logo';
import { ArrowLeftRight, Zap, Database, LayoutDashboard, Library as LibraryIcon } from 'lucide-react';

export function Navbar() {
  const { pathname } = useLocation();
  const isActive = (path: string) => {
    if (path === '/') return pathname === '/';
    return pathname.startsWith(path);
  };

  return (
    <nav className="sticky top-0 z-50 h-[60px] bg-surface/80 backdrop-blur-md backdrop-saturate-150 border-b border-border/80 shadow-[0_4px_20px_-4px_rgba(26,18,8,0.05)] transition-all">
      <div className="max-w-7xl mx-auto px-6 h-full flex items-center justify-between">

        {/* Left: Brand Wordmark with Official GenQ Logo */}
        <Link to="/" className="flex items-center gap-2.5 group">
          <div className="w-8 h-8 rounded-[8px] bg-surface-secondary border border-border flex items-center justify-center text-accent group-hover:border-accent transition-colors shadow-custom-sm">
            <Logo size={18} className="text-accent" />
          </div>
          <div className="flex flex-col">
            <div className="flex items-baseline gap-1.5 leading-none">
              <span className="font-heading font-bold text-[20px] text-fg tracking-tight">GenQ</span>
              <span className="font-body font-medium text-[14px] text-accent tracking-normal">Analytics</span>
            </div>
            <span className="font-body text-[9px] uppercase tracking-[0.12em] text-muted font-medium mt-0.5">
              Academic &amp; Autonomous Intelligence
            </span>
          </div>
        </Link>

        {/* Center: Scholarly Nav Links */}
        <div className="hidden lg:flex items-center gap-1.5">
          <Link
            to="/dashboard"
            className={`font-body text-[13px] px-3 py-1.5 rounded-[8px] flex items-center gap-1.5 transition-all ${
              isActive('/dashboard')
                ? 'bg-surface-secondary text-accent font-semibold shadow-custom-sm border border-border'
                : 'text-muted hover:text-fg hover:bg-surface-secondary/40'
            }`}
          >
            <LayoutDashboard size={13} className={isActive('/dashboard') ? 'text-accent' : 'text-muted'} />
            Dashboard
          </Link>

          <Link
            to="/library"
            className={`font-body text-[13px] px-3 py-1.5 rounded-[8px] flex items-center gap-1.5 transition-all ${
              isActive('/library')
                ? 'bg-surface-secondary text-accent font-semibold shadow-custom-sm border border-border'
                : 'text-muted hover:text-fg hover:bg-surface-secondary/40'
            }`}
          >
            <LibraryIcon size={13} className={isActive('/library') ? 'text-accent' : 'text-muted'} />
            Archives
          </Link>

          <Link
            to="/insights"
            className={`font-body text-[13px] px-3 py-1.5 rounded-[8px] flex items-center gap-1.5 transition-all ${
              isActive('/insights')
                ? 'bg-surface-secondary text-accent font-semibold shadow-custom-sm border border-border'
                : 'text-muted hover:text-fg hover:bg-surface-secondary/40'
            }`}
          >
            <Zap size={13} className={isActive('/insights') ? 'text-accent' : 'text-muted'} />
            Insights Feed
          </Link>

          <Link
            to="/compare"
            className={`font-body text-[13px] px-3 py-1.5 rounded-[8px] flex items-center gap-1.5 transition-all ${
              isActive('/compare')
                ? 'bg-surface-secondary text-accent font-semibold shadow-custom-sm border border-border'
                : 'text-muted hover:text-fg hover:bg-surface-secondary/40'
            }`}
          >
            <ArrowLeftRight size={13} className={isActive('/compare') ? 'text-accent' : 'text-muted'} />
            Comparative Delta
          </Link>

          <Link
            to="/playground"
            className={`font-body text-[13px] px-3 py-1.5 rounded-[8px] flex items-center gap-1.5 transition-all ${
              isActive('/playground')
                ? 'bg-surface-secondary text-accent font-semibold shadow-custom-sm border border-border'
                : 'text-muted hover:text-fg hover:bg-surface-secondary/40'
            }`}
          >
            <Database size={13} className={isActive('/playground') ? 'text-accent' : 'text-muted'} />
            Data Query Studio
          </Link>
        </div>

        {/* Right: Primary Deposit Action Button */}
        <div className="flex items-center gap-3">
          <Link to="/upload">
            <Button size="sm" variant="primary">
              Deposit Dataset
            </Button>
          </Link>
        </div>

      </div>
    </nav>
  );
}
