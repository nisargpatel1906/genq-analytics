export function DataPrivacy() {
  return (
    <div className="max-w-4xl mx-auto py-20 px-6">
      <h1 className="font-heading text-4xl text-fg mb-8">Data Privacy</h1>
      <div className="prose prose-invert max-w-none text-fg/80 space-y-6">
        <p>
          Your privacy is our highest priority. GenQ Analytics is built on a privacy-first architecture.
        </p>
        
        <h2 className="font-heading text-2xl text-fg mt-8 mb-4">Zero Data Retention</h2>
        <p>
          We do not store, log, or transmit your uploaded CSV data to any external servers. All processing 
          is done locally within your environment.
        </p>

        <h2 className="font-heading text-2xl text-fg mt-8 mb-4">No Third-Party Trackers</h2>
        <p>
          Our application does not include any third-party tracking scripts, analytics, or advertising cookies.
        </p>

        <h2 className="font-heading text-2xl text-fg mt-8 mb-4">Security by Design</h2>
        <p>
          Because our AI models run locally, you are entirely protected against cloud data breaches, 
          man-in-the-middle attacks, and unauthorized access by service providers.
        </p>
      </div>
    </div>
  );
}
