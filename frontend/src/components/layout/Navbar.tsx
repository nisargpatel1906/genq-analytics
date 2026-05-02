import { Link } from 'react-router-dom';
import { Search } from 'lucide-react';
import { Button } from '../ui/Button';

export function Navbar() {
  return (
    <nav className="sticky top-0 z-50 h-[56px] bg-bg/80 backdrop-blur-[12px] border-b border-border">
      <div className="max-w-7xl mx-auto px-6 h-full flex items-center justify-between">
        
        {/* Left: Logo */}
        <Link to="/" className="font-heading font-bold text-[20px] text-fg tracking-tight">
          GenQ Analytics
        </Link>
        
        {/* Center: Nav links */}
        <div className="hidden md:flex items-center gap-8">
          <Link to="/upload" className="font-body text-[13px] text-fg hover:text-accent transition-colors">Upload</Link>
          <Link to="/dashboard" className="font-body text-[13px] text-fg hover:text-accent transition-colors">Dashboard</Link>
          <Link to="/library" className="font-body text-[13px] text-fg hover:text-accent transition-colors">Library</Link>
        </div>
        
        {/* Right: Search & Action */}
        <div className="flex items-center gap-4">
          <Link to="/upload">
            <Button size="sm">New Analysis</Button>
          </Link>
        </div>
        
      </div>
    </nav>
  );
}
