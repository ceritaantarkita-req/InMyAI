import net from 'node:net'

export function parsePortOverride(name, value, legacyPort) {
  if (value === undefined) return legacyPort
  if (typeof value !== 'string' || !/^[1-9]\d*$/.test(value)) {
    throw new Error(`${name} must be an integer between 1 and 65535.`)
  }
  const port = Number(value)
  if (!Number.isSafeInteger(port) || port > 65535) {
    throw new Error(`${name} must be an integer between 1 and 65535.`)
  }
  return port
}

export function resolveInMyAIPorts(environment = process.env) {
  return {
    web: parsePortOverride('INMYAI_WEB_PORT', environment.INMYAI_WEB_PORT, 3000),
    api: parsePortOverride('INMYAI_API_PORT', environment.INMYAI_API_PORT, 8000),
  }
}

export function resolveWebEnvironment(environment = process.env) {
  const { api } = resolveInMyAIPorts(environment)
  return {
    ...environment,
    NEXT_PUBLIC_API_URL: environment.NEXT_PUBLIC_API_URL || `http://127.0.0.1:${api}`,
  }
}

export function assertLoopbackPortAvailable(name, port) {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.once('error', error => {
      const code = typeof error === 'object' && error && 'code' in error
        ? error.code
        : 'UNKNOWN'
      reject(new Error(`${name} cannot bind 127.0.0.1:${port}: ${code}.`, { cause: error }))
    })
    server.listen({ host: '127.0.0.1', port, exclusive: true }, () => {
      server.close(error => {
        if (error) reject(error)
        else resolve()
      })
    })
  })
}
