import log from 'loglevel'
import type { Logger } from 'loglevel'

// Set log level based on environment
log.setLevel(import.meta.env.DEV ? 'debug' : 'warn')

// Create named loggers for different modules
export const createLogger = (name: string): Logger => log.getLogger(name)

// Pre-configured loggers
export const authLogger: Logger = createLogger('auth')
export const apiLogger: Logger = createLogger('api')

export default log
