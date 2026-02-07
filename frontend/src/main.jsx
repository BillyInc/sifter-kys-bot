import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthProvider } from './contexts/AuthContext.jsx'
import { WalletContextProvider } from './contexts/WalletContext.jsx'
import App from './App.jsx'
import './index.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <WalletContextProvider>
        <App />
      </WalletContextProvider>
    </AuthProvider>
  </StrictMode>,
)
