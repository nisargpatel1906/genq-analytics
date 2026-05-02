import { Link } from 'react-router-dom';

export function Footer() {
  return (
    <footer className="border-t border-border bg-bg">
      <div className="max-w-7xl mx-auto px-6 h-[56px] flex items-center justify-between">
        <div className="font-body text-[11px] text-fg/50">
          © 2026 GenQ Analytics. Engineered for Precision.
        </div>
        <div className="flex items-center gap-6 font-body text-[11px] text-fg/50">
          <Link to="/methodology" className="hover:text-fg transition-colors">Methodology</Link>
          <Link to="/privacy" className="hover:text-fg transition-colors">Data Privacy</Link>
          <Link to="/terms" className="hover:text-fg transition-colors">Terms of Service</Link>
        </div>
      </div>
    </footer>
  );
}
