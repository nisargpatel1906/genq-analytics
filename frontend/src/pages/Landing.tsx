import { Link } from 'react-router-dom';
import { Button } from '../components/ui/Button';

export function Landing() {
  return (
    <div className="w-full h-full flex items-center justify-center py-20 px-6">
      <div className="max-w-7xl w-full mx-auto flex flex-col items-center justify-center text-center">
        
        <div className="flex flex-col items-center space-y-8 max-w-2xl">
          {/* Removed pinging indicator as requested */}
          
          <h1 className="font-heading text-[56px] leading-[1.1] text-fg tracking-tight">
            From Raw Data to<br/>
            <span className="italic text-accent">Human Insight.</span><br/>
            No Code Required.
          </h1>
          
          <p className="font-body text-[15px] text-fg/70 max-w-[420px] leading-[1.6]">
            Upload your CSV and let our AI handle the analysis, visualization, and report writing. Experience the quiet luxury of absolute precision without the cognitive load of manual data wrangling.
          </p>
          
          <div className="flex items-center justify-center gap-4 pt-4">
            <Link to="/upload">
              <Button size="lg">Get Started &rarr;</Button>
            </Link>
            <Link to="/methodology">
              <Button variant="ghost" size="lg">View Methodology</Button>
            </Link>
          </div>
        </div>

      </div>
    </div>
  );
}
