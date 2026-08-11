import process from 'node:process'

export function consumeLifecycleEnvironment(environment = process.env) {
  const token = environment.INMY_LIFECYCLE_SHUTDOWN_TOKEN
  if (!token) return null

  const childEnvironment = { ...environment }
  delete environment.INMY_LIFECYCLE_SHUTDOWN_TOKEN
  return {
    childEnvironment,
    release() {
      delete childEnvironment.INMY_LIFECYCLE_SHUTDOWN_TOKEN
    },
  }
}
