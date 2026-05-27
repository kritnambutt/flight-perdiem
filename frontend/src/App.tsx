import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { ThemeProvider, useTheme } from './contexts/ThemeContext'
import { LoginPage } from './pages/LoginPage'
import { RunPage } from './pages/RunPage'
import { ResultsPage } from './pages/ResultsPage'
import { ExceptionsPage } from './pages/ExceptionsPage'
import { ConfigPage } from './pages/ConfigPage'
import { AuditPage } from './pages/AuditPage'
import { Navbar, NavbarDivider, NavbarItem, NavbarSection, NavbarSpacer } from './components/ui/navbar'
import { StackedLayout } from './components/ui/stacked-layout'

const NAV_LINKS = [
  { to: '/', label: 'Run' },
  { to: '/config', label: 'Config' },
  { to: '/audit', label: 'Audit' },
]

const SunIcon = () => (
  <svg data-slot="icon" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
    <path d="M10 2a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 10 2ZM10 15a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 10 15ZM10 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM15.657 5.404a.75.75 0 1 0-1.06-1.06l-1.061 1.06a.75.75 0 0 0 1.06 1.06l1.06-1.06ZM6.464 14.596a.75.75 0 1 0-1.06-1.06l-1.061 1.06a.75.75 0 0 0 1.06 1.06l1.06-1.06ZM18 10a.75.75 0 0 1-.75.75h-1.5a.75.75 0 0 1 0-1.5h1.5A.75.75 0 0 1 18 10ZM5 10a.75.75 0 0 1-.75.75h-1.5a.75.75 0 0 1 0-1.5h1.5A.75.75 0 0 1 5 10ZM14.596 15.657a.75.75 0 0 0 1.06-1.06l-1.06-1.061a.75.75 0 1 0-1.06 1.06l1.06 1.06ZM5.404 6.464a.75.75 0 0 0 1.06-1.06l-1.06-1.061a.75.75 0 1 0-1.061 1.06l1.06 1.06Z" />
  </svg>
)

const MoonIcon = () => (
  <svg data-slot="icon" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
    <path
      fillRule="evenodd"
      d="M7.455 2.004a.75.75 0 0 1 .26.77 7 7 0 0 0 9.958 7.967.75.75 0 0 1 1.067.853A8.5 8.5 0 1 1 6.647 1.921a.75.75 0 0 1 .808.083Z"
      clipRule="evenodd"
    />
  </svg>
)

const ThemeToggle = () => {
  const { theme, toggleTheme } = useTheme()
  return (
    <NavbarItem onClick={toggleTheme} aria-label="Toggle dark mode">
      {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
    </NavbarItem>
  )
}

const AppNavbar = () => {
  const { user, logout } = useAuth()
  const { pathname } = useLocation()

  return (
    <Navbar>
      <NavbarItem href="/" className="font-bold tracking-tight text-sm">
        Per Diem · DMK
      </NavbarItem>
      <NavbarDivider />
      <NavbarSection>
        {NAV_LINKS.map(({ to, label }) => (
          <NavbarItem key={to} href={to} current={pathname === to}>
            {label}
          </NavbarItem>
        ))}
      </NavbarSection>
      <NavbarSpacer />
      <NavbarSection>
        <ThemeToggle />
        <span className="text-xs text-zinc-500 dark:text-zinc-400">{user}</span>
        <NavbarItem onClick={logout}>Sign out</NavbarItem>
      </NavbarSection>
    </Navbar>
  )
}

const AppSidebar = () => {
  const { pathname } = useLocation()
  return (
    <div className="flex flex-col gap-1 px-4 py-4">
      {NAV_LINKS.map(({ to, label }) => (
        <NavbarItem key={to} href={to} current={pathname === to}>
          {label}
        </NavbarItem>
      ))}
    </div>
  )
}

const AuthGuard = ({ children }: { children: React.ReactNode }) => {
  const { user, loading } = useAuth()
  if (loading)
    return (
      <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 flex items-center justify-center text-zinc-400 text-sm">
        Loading…
      </div>
    )
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

export const App = () => (
  <ThemeProvider>
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/*"
          element={
            <AuthGuard>
              <StackedLayout navbar={<AppNavbar />} sidebar={<AppSidebar />}>
                <Routes>
                  <Route path="/" element={<RunPage />} />
                  <Route path="/runs/:runId/results" element={<ResultsPage />} />
                  <Route path="/runs/:runId/exceptions" element={<ExceptionsPage />} />
                  <Route path="/config" element={<ConfigPage />} />
                  <Route path="/audit" element={<AuditPage />} />
                </Routes>
              </StackedLayout>
            </AuthGuard>
          }
        />
      </Routes>
    </AuthProvider>
  </ThemeProvider>
)
