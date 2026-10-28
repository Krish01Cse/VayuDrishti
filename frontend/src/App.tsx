import React, { useEffect, useRef } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { Navbar } from './components/Navbar';
import { Footer } from './components/Footer';
import { SubmitReportPage } from './pages/SubmitReportPage';
import { MyReportsPage } from './pages/MyReportsPage';
import { MapPage } from './pages/MapPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { ReportFormProvider } from './context/ReportFormContext';

// Scroll to top + page-transition animation on route change
const PageTransition: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (ref.current) {
      ref.current.style.animation = 'none';
      // Trigger reflow to restart the animation
      void ref.current.offsetHeight;
      ref.current.style.animation = 'page-enter 0.35s cubic-bezier(0.16, 1, 0.3, 1)';
    }
  }, [location.pathname]);

  return (
    <div ref={ref} style={{ width: '100%' }}>
      {children}
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <ReportFormProvider>
      <BrowserRouter>
        <div className="app-container">
          <Navbar />
          <main className="main-content">
            <PageTransition>
              <Routes>
                <Route path="/" element={<Navigate to="/submit" replace />} />
                <Route path="/submit" element={<SubmitReportPage />} />
                <Route path="/my-reports" element={<MyReportsPage />} />
                <Route path="/map" element={<MapPage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Routes>
            </PageTransition>
          </main>
          <Footer />
        </div>
      </BrowserRouter>
    </ReportFormProvider>
  );
};

export default App;
