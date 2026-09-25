import { Link, useLocation } from 'react-router-dom';
import { Button } from '../ui/Button';
import { ArrowLeftRight, Zap, Database } from 'lucide-react';

export function Navbar() {
  const { pathname } = useLocation();
  const isActive = (path: string) => pathname.startsWith(path);

  return (
    <nav className="sticky top-0 z-50 h-[56px] bg-bg/80 backdrop-blur-[12px] border-b border-border">
      <div className="max-w-7xl mx-auto px-6 h-full flex items-center justify-between">

        {/* Left: Logo */}
        <Link to="/" className="font-heading font-bold text-[20px] text-fg tracking-tight">
          GenQ Analytics
        </Link>

        {/* Center: Nav links */}
        <div className="hidden md:flex items-center gap-6">
          <Link to="/upload" className={`font-body text-[13px] transition-colors ${isActive('/upload') ? 'text-accent font-semibold' : 'text-fg hover:text-accent'}`}>
            Upload
          </Link>
          <Link to="/dashboard" className={`font-body text-[13px] transition-colors ${isActive('/dashboard') ? 'text-accent font-semibold' : 'text-fg hover:text-accent'}`}>
            Dashboard
          </Link>
          <Link to="/library" className={`font-body text-[13px] transition-colors ${isActive('/library') ? 'text-accent font-semibold' : 'text-fg hover:text-accent'}`}>
            Library
          </Link>
          {/* New analytics team pages */}
          <Link to="/insights" className={`font-body text-[13px] flex items-center gap-1.5 transition-colors ${isActive('/insights') ? 'text-amber-500 font-semibold' : 'text-fg hover:text-amber-500'}`}>
            <Zap size={12} className="text-amber-400" /> Insights
          </Link>
          <Link to="/compare" className={`font-body text-[13px] flex items-center gap-1.5 transition-colors ${isActive('/compare') ? 'text-violet-500 font-semibold' : 'text-fg hover:text-violet-500'}`}>
            <ArrowLeftRight size={12} className="text-violet-400" /> Compare
          </Link>
          <Link to="/playground" className={`font-body text-[13px] flex items-center gap-1.5 transition-colors ${isActive('/playground') ? 'text-emerald-500 font-semibold' : 'text-fg hover:text-emerald-500'}`}>
            <Database size={12} className="text-emerald-400" /> Playground
          </Link>
        </div>

        {/* Right */}
        <div className="flex items-center gap-4">
          <Link to="/upload">
            <Button size="sm">New Analysis</Button>
          </Link>
        </div>

      </div>
    </nav>
  );
}
