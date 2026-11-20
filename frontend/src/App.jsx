import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AppProvider } from './context.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import Layout from './components/Layout.jsx'
import Home from './pages/Home.jsx'
import Services from './pages/Services.jsx'
import ServiceDetail from './pages/ServiceDetail.jsx'
import Cart from './pages/Cart.jsx'
import ApplyAll from './pages/ApplyAll.jsx'
import Checkout from './pages/Checkout.jsx'
import Confirmation from './pages/Confirmation.jsx'
import Pay from './pages/Pay.jsx'
import Track from './pages/Track.jsx'
import { About, Contact, Faq, Legal, NotFound } from './pages/Static.jsx'

export default function App() {
  return (
    <BrowserRouter basename="/app">
      <AppProvider>
        <ErrorBoundary>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Home />} />
              <Route path="services" element={<Services />} />
              <Route path="services/:slug" element={<ServiceDetail />} />
              <Route path="cart" element={<Cart />} />
              <Route path="apply" element={<ApplyAll />} />
              <Route path="apply/:itemKey" element={<Navigate to="/apply" replace />} />
              <Route path="checkout" element={<Checkout />} />
              <Route path="order/:orderNumber" element={<Confirmation />} />
              <Route path="pay/:orderNumber" element={<Pay />} />
              <Route path="track" element={<Track />} />
              <Route path="about" element={<About />} />
              <Route path="contact" element={<Contact />} />
              <Route path="faq" element={<Faq />} />
              <Route path="privacy" element={<Legal pageName="privacy" />} />
              <Route path="terms" element={<Legal pageName="terms" />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </ErrorBoundary>
      </AppProvider>
    </BrowserRouter>
  )
}
