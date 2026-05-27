import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { Button } from '../components/ui/button'
import { Field, Label, ErrorMessage } from '../components/ui/fieldset'
import { Input } from '../components/ui/input'
import { Heading } from '../components/ui/heading'
import { Text } from '../components/ui/text'

export const LoginPage = () => {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const { login } = useAuth()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await login(password)
      navigate('/')
    } catch {
      setError('Incorrect password. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 flex items-center justify-center px-4">
      <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-md ring-1 ring-zinc-950/5 dark:ring-white/10 p-8 w-full max-w-sm">
        <Heading>Per Diem System</Heading>
        <Text className="mt-1 mb-6">AirAsia CCD — DMK Base</Text>

        <form onSubmit={handleSubmit} className="space-y-5">
          <Field>
            <Label>Admin password</Label>
            <Input
              type="password"
              autoFocus
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
              disabled={loading}
            />
          </Field>

          {error && <ErrorMessage>{error}</ErrorMessage>}

          <Button type="submit" color="blue" disabled={loading || !password} className="w-full">
            {loading ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>
      </div>
    </div>
  )
}
