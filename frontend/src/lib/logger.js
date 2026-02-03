import log from 'loglevel'

// Set log level based on environment
log.setLevel(import.meta.env.DEV ? 'debug' : 'warn')

// Create named loggers for different modules
export const createLogger = (name) => log.getLogger(name)

// Pre-configured loggers
export const authLogger = createLogger('auth')
export const apiLogger = createLogger('api')

export default log
