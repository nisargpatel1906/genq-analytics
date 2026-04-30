import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { Landing } from './pages/Landing';
import { Upload } from './pages/Upload';
import { Dashboard } from './pages/Dashboard';
import { Report } from './pages/Report';
import { Library } from './pages/Library';
import { Methodology } from './pages/Methodology';
import { DataPrivacy } from './pages/DataPrivacy';
import { TermsOfService } from './pages/TermsOfService';
import { Navbar } from './components/layout/Navbar';
import { Footer } from './components/layout/Footer';

function App() {
  return (
    <Router>
      <div className="flex flex-col min-h-screen">
        <Navbar />
        <main className="flex-1">
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/upload" element={<Upload />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/reports/:id?" element={<Report />} />
            <Route path="/library" element={<Library />} />
            <Route path="/methodology" element={<Methodology />} />
            <Route path="/privacy" element={<DataPrivacy />} />
            <Route path="/terms" element={<TermsOfService />} />
          </Routes>
        </main>
        <Footer />
      </div>
    </Router>
  );
}

export default App;
