import { useState } from 'react'
import { Mail, Lock, Eye, EyeOff, Loader2, ArrowLeft } from 'lucide-react'

export default function Auth({ onSignIn, onSignUp, onResetPassword, onUpdatePassword, isPasswordRecovery }) {
  const [mode, setMode] = useState(isPasswordRecovery ? 'update-password' : 'signin') // signin, signup, forgot, update-password
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [message, setMessage] = useState(null)

  const resetForm = () => {
    setEmail('')
    setPassword('')
    setConfirmPassword('')
    setError(null)
    setMessage(null)
  }

  const switchMode = (newMode) => {
    resetForm()
    setMode(newMode)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)
    setMessage(null)
    setLoading(true)

    try {
      if (mode === 'forgot') {
        if (!email) {
          throw new Error('Please enter your email')
        }
        const { error } = await onResetPassword(email)
        if (error) throw error
        setMessage('Check your email for the password reset link!')
        setEmail('')
      } else if (mode === 'update-password') {
        if (!password) {
          throw new Error('Please enter a new password')
        }
        if (password.length < 6) {
          throw new Error('Password must be at least 6 characters')
        }
        if (password !== confirmPassword) {
          throw new Error('Passwords do not match')
        }
        const { error } = await onUpdatePassword(password)
        if (error) throw error
        setMessage('Password updated successfully!')
        resetForm()
      } else if (mode === 'signup') {
        if (!email || !password) {
          throw new Error('Please fill in all fields')
        }
        if (password.length < 6) {
          throw new Error('Password must be at least 6 characters')
        }
        if (password !== confirmPassword) {
          throw new Error('Passwords do not match')
        }
        const { error } = await onSignUp(email, password)
        if (error) throw error
        setMessage('Check your email for the confirmation link!')
        resetForm()
      } else {
        if (!email || !password) {
          throw new Error('Please fill in all fields')
        }
        const { error } = await onSignIn(email, password)
        if (error) throw error
      }
    } catch (err) {
      setError(err.message || 'An error occurred')
    } finally {
      setLoading(false)
    }
  }

  const getTitle = () => {
    switch (mode) {
      case 'signup': return 'Create your account'
      case 'forgot': return 'Reset your password'
      case 'update-password': return 'Set new password'
      default: return 'Sign in to continue'
    }
  }

  const getButtonText = () => {
    if (loading) {
      switch (mode) {
        case 'signup': return 'Creating account...'
        case 'forgot': return 'Sending reset link...'
        case 'update-password': return 'Updating password...'
        default: return 'Signing in...'
      }
    }
    switch (mode) {
      case 'signup': return 'Create Account'
      case 'forgot': return 'Send Reset Link'
      case 'update-password': return 'Update Password'
      default: return 'Sign In'
    }
  }

  const showEmailField = mode === 'signin' || mode === 'signup' || mode === 'forgot'
  const showPasswordField = mode === 'signin' || mode === 'signup' || mode === 'update-password'
  const showConfirmPassword = mode === 'signup' || mode === 'update-password'

  return (
    <div className="min-h-screen bg-black flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white">
            SIFTER <span className="text-purple-500">KYS</span>
          </h1>
          <p className="text-gray-400 mt-2">{getTitle()}</p>
        </div>

        <div className="bg-white/5 border border-white/10 rounded-xl p-6">
          {(mode === 'forgot' || mode === 'update-password') && (
            <button
              onClick={() => switchMode('signin')}
              className="flex items-center gap-2 text-sm text-gray-400 hover:text-white mb-4"
            >
              <ArrowLeft size={16} />
              Back to sign in
            </button>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {showEmailField && (
              <div>
                <label className="block text-sm font-medium mb-2 text-white">Email</label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={18} />
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="w-full bg-white/10 border border-white/20 rounded-lg pl-10 pr-4 py-3 text-sm text-white placeholder-gray-400 focus:outline-none focus:border-purple-500 focus:bg-white/15"
                    disabled={loading}
                  />
                </div>
              </div>
            )}

            {showPasswordField && (
              <div>
                <label className="block text-sm font-medium mb-2 text-white">
                  {mode === 'update-password' ? 'New Password' : 'Password'}
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={18} />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={mode === 'update-password' ? 'Enter new password' : 'Enter your password'}
                    className="w-full bg-white/10 border border-white/20 rounded-lg pl-10 pr-12 py-3 text-sm text-white placeholder-gray-400 focus:outline-none focus:border-purple-500 focus:bg-white/15"
                    disabled={loading}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-white"
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>
            )}

            {showConfirmPassword && (
              <div>
                <label className="block text-sm font-medium mb-2 text-white">Confirm Password</label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={18} />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Confirm your password"
                    className="w-full bg-white/10 border border-white/20 rounded-lg pl-10 pr-4 py-3 text-sm text-white placeholder-gray-400 focus:outline-none focus:border-purple-500 focus:bg-white/15"
                    disabled={loading}
                  />
                </div>
              </div>
            )}

            {error && (
              <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
                <p className="text-red-400 text-sm">{error}</p>
              </div>
            )}

            {message && (
              <div className="p-3 bg-green-500/10 border border-green-500/20 rounded-lg">
                <p className="text-green-400 text-sm">{message}</p>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full px-4 py-3 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-600/50 rounded-lg font-semibold transition flex items-center justify-center gap-2"
            >
              {loading && <Loader2 size={18} className="animate-spin" />}
              {getButtonText()}
            </button>
          </form>

          {mode === 'signin' && (
            <div className="mt-4 text-center">
              <button
                onClick={() => switchMode('forgot')}
                className="text-sm text-purple-400 hover:text-purple-300"
              >
                Forgot your password?
              </button>
            </div>
          )}

          {(mode === 'signin' || mode === 'signup') && (
            <div className="mt-6 text-center">
              <button
                onClick={() => switchMode(mode === 'signin' ? 'signup' : 'signin')}
                className="text-sm text-gray-400 hover:text-white"
              >
                {mode === 'signup' ? 'Already have an account? Sign in' : "Don't have an account? Sign up"}
              </button>
            </div>
          )}
        </div>

        <p className="text-center text-xs text-gray-500 mt-6">
          By signing in, you agree to our Terms of Service
        </p>
      </div>
    </div>
  )
}