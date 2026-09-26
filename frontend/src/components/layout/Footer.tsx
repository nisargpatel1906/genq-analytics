import { Link } from 'react-router-dom';
import { Logo } from '../ui/Logo';

export function Footer() {
  return (
    <footer className="border-t border-border bg-surface/60">
      <div className="max-w-7xl mx-auto px-6 h-[56px] flex items-center justify-between">
        <div className="font-body text-[12px] text-muted flex items-center gap-2">
          <Logo size={14} className="text-accent" />
          <span>
            © 2026 <span className="font-medium text-fg">GenQ Analytics</span> — Academic &amp; Autonomous Intelligence.
          </span>
        </div>
        <div className="flex items-center gap-6 font-body text-[12px] text-muted">
          <Link to="/methodology" className="hover:text-fg transition-colors">Methodology</Link>
          <Link to="/privacy" className="hover:text-fg transition-colors">Data Privacy</Link>
          <Link to="/terms" className="hover:text-fg transition-colors">Terms of Service</Link>
        </div>
      </div>
    </footer>
  );
}
