import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import { ErrorBoundary } from './components/ErrorBoundary'
import { installMockWallet } from './features/wallet/devMockWallet'
import { WalletProvider } from './features/wallet/WalletContext'
import './styles/globals.css'

// Development only, and only with ?mockWallet=1 in the URL. Stripped from
// production builds entirely. See devMockWallet.ts for the safety gates.
installMockWallet()

const container = document.getElementById('root')

if (!container) {
  throw new Error('Root element #root not found in index.html')
}

createRoot(container).render(
  <StrictMode>
    {/* Outermost net. If the wallet provider itself throws, the user still
        sees a readable message instead of a blank page. */}
    <ErrorBoundary>
      <WalletProvider>
        <App />
      </WalletProvider>
    </ErrorBoundary>
  </StrictMode>,
)
