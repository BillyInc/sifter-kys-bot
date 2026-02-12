import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { supabase } from '../lib/supabase';
import { authLogger } from '../lib/logger';

const AuthContext = createContext({})

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)
  const [authEvent, setAuthEvent] = useState(null)

  useEffect(() => {
    // Get initial session
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session)
      setUser(session?.user ?? null)
      setLoading(false)
      authLogger.debug('Initial session loaded', { userId: session?.user?.id })
    })

    // Listen for auth changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      async (event, session) => {
        authLogger.info(`Auth event: ${event}`, { userId: session?.user?.id })
        setAuthEvent(event)
        setSession(session)
        setUser(session?.user ?? null)
        setLoading(false)
      }
    )

    return () => subscription.unsubscribe()
  }, [])

  const signUp = useCallback(async (email, password) => {
    authLogger.debug('Attempting sign up', { email })
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
    })
    if (error) {
      authLogger.warn('Sign up failed', { email, error: error.message })
    } else {
      authLogger.info('Sign up successful', { email })
    }
    return { data, error }
  }, [])

  const signIn = useCallback(async (email, password) => {
    authLogger.debug('Attempting sign in', { email })
    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    })
    if (error) {
      authLogger.warn('Sign in failed', { email, error: error.message })
    } else {
      authLogger.info('Sign in successful', { email })
    }
    return { data, error }
  }, [])

  const signOut = useCallback(async () => {
    authLogger.debug('Signing out')
    const { error } = await supabase.auth.signOut()
    if (error) {
      authLogger.warn('Sign out failed', { error: error.message })
    } else {
      authLogger.info('Sign out successful')
    }
    return { error }
  }, [])

  const resetPassword = useCallback(async (email, redirectTo) => {
    authLogger.debug('Requesting password reset', { email })
    const { data, error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: redirectTo || `${window.location.origin}/reset-password`,
    })
    if (error) {
      authLogger.warn('Password reset request failed', { email, error: error.message })
    } else {
      authLogger.info('Password reset email sent', { email })
    }
    return { data, error }
  }, [])

  const updatePassword = useCallback(async (newPassword) => {
    authLogger.debug('Updating password')
    const { data, error } = await supabase.auth.updateUser({
      password: newPassword,
    })
    if (error) {
      authLogger.warn('Password update failed', { error: error.message })
    } else {
      authLogger.info('Password updated successfully')
    }
    return { data, error }
  }, [])

  const refreshSession = useCallback(async () => {
    authLogger.debug('Refreshing session')
    const { data, error } = await supabase.auth.refreshSession()
    if (error) {
      authLogger.warn('Session refresh failed', { error: error.message })
    } else {
      authLogger.debug('Session refreshed')
    }
    return { data, error }
  }, [])

  const getAccessToken = useCallback(() => {
    return session?.access_token ?? null
  }, [session])

  const value = {
    user,
    session,
    loading,
    authEvent,
    signUp,
    signIn,
    signOut,
    resetPassword,
    updatePassword,
    refreshSession,
    getAccessToken,
    isAuthenticated: !!user,
    isPasswordRecovery: authEvent === 'PASSWORD_RECOVERY',
  }

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}
