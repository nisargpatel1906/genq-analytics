export function TermsOfService() {
  return (
    <div className="max-w-4xl mx-auto py-20 px-6">
      <h1 className="font-heading text-4xl text-fg mb-8">Terms of Service</h1>
      <div className="prose prose-invert max-w-none text-fg/80 space-y-6">
        <p>
          Welcome to GenQ Analytics. By accessing or using our application, you agree to be bound by these Terms of Service.
        </p>
        
        <h2 className="font-heading text-2xl text-fg mt-8 mb-4">1. License</h2>
        <p>
          GenQ Analytics is provided under the GNU General Public License v3.0 (GPLv3). 
          You are free to use, modify, and distribute the software in accordance with the terms of the license.
        </p>

        <h2 className="font-heading text-2xl text-fg mt-8 mb-4">2. Disclaimer of Warranties</h2>
        <p>
          The application is provided "as is", without warranty of any kind, express or implied. 
          We do not guarantee that the application will be error-free or that any AI-generated insights 
          will be 100% accurate.
        </p>

        <h2 className="font-heading text-2xl text-fg mt-8 mb-4">3. Limitation of Liability</h2>
        <p>
          In no event shall GenQ Analytics or its contributors be liable for any direct, indirect, 
          incidental, special, exemplary, or consequential damages arising in any way out of the use of this software.
        </p>
      </div>
    </div>
  );
}
