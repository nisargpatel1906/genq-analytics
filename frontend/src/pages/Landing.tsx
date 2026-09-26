import { Link } from 'react-router-dom';
import { Button } from '../components/ui/Button';
import { Logo } from '../components/ui/Logo';

export function Landing() {
  return (
    <div className="w-full h-full flex items-center justify-center py-24 px-6">
      <div className="max-w-7xl w-full mx-auto flex flex-col items-center justify-center text-center">
        
        <div className="flex flex-col items-center space-y-8 max-w-3xl">
          {/* Scholarly Brand Badge */}
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-[6px] bg-surface-secondary border border-border shadow-custom-sm">
            <Logo size={14} className="text-accent" />
            <span className="font-body text-[11px] font-semibold tracking-[0.12em] uppercase text-accent">
              Academic &amp; Autonomous Intelligence
            </span>
          </div>
          
          <h1 className="font-heading text-[48px] sm:text-[58px] md:text-[64px] leading-[1.12] text-fg tracking-tight">
            From Raw Data to<br />
            <span className="italic text-accent">Scholarly Insight.</span><br />
            No Code Required.
          </h1>
          
          <p className="font-body text-[16px] text-muted max-w-[540px] leading-[1.7]">
            Deposit your structured dataset and let our multi-agent quantitative team orchestrate statistical inference, causal hypothesis testing, and executive strategic synthesis.
          </p>
          
          <div className="flex flex-wrap items-center justify-center gap-4 pt-4">
            <Link to="/upload">
              <Button size="lg" variant="primary">
                Deposit Dataset &rarr;
              </Button>
            </Link>
            <Link to="/methodology">
              <Button variant="outlined" size="lg">
                View Methodology
              </Button>
            </Link>
          </div>
        </div>

      </div>
    </div>
  );
}
