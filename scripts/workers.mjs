import { spawn } from "node:child_process"
import { existsSync } from "node:fs"
import { join } from "node:path"
import process from "node:process"
import readline from "node:readline"

const root = process.cwd()
const isWindows = process.platform === "win32"
const python = existsSync(join(root, ".venv", "Scripts", "python.exe"))
  ? join(root, ".venv", "Scripts", "python.exe")
  : "python"

const services = [
  {
    name: "worker",
    color: "\x1b[32m",
    command: python,
    args: ["-m", "joborchestrator.worker"],
  },
  {
    name: "ranking",
    color: "\x1b[33m",
    command: python,
    args: ["-m", "joborchestrator.ranking.worker"],
  },
]

const reset = "\x1b[0m"
const children = new Map()
let shuttingDown = false

function prefixStream(service, stream, output) {
  const rl = readline.createInterface({ input: stream })
  rl.on("line", (line) => {
    output.write(`${service.color}[${service.name.padEnd(7)}]${reset} ${line}\n`)
  })
}

function start(service) {
  const child = spawn(service.command, service.args, {
    cwd: root,
    env: process.env,
    shell: isWindows,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: false,
  })

  children.set(service.name, child)
  prefixStream(service, child.stdout, process.stdout)
  prefixStream(service, child.stderr, process.stderr)

  child.on("error", (error) => {
    console.error(`${service.color}[${service.name.padEnd(7)}]${reset} failed to start: ${error.message}`)
  })

  child.on("exit", (code, signal) => {
    children.delete(service.name)
    if (shuttingDown) {
      return
    }
    const reason = signal ? `signal ${signal}` : `code ${code}`
    console.error(`${service.color}[${service.name.padEnd(7)}]${reset} exited with ${reason}; stopping the rest.`)
    stopAll(code || 1)
  })
}

function stopAll(exitCode = 0) {
  if (shuttingDown) {
    return
  }
  shuttingDown = true
  for (const child of children.values()) {
    if (isWindows) {
      spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], { stdio: "ignore", windowsHide: true })
    } else {
      child.kill("SIGINT")
    }
  }
  setTimeout(() => {
    for (const child of children.values()) {
      if (!isWindows) {
        child.kill()
      }
    }
    process.exit(exitCode)
  }, 3000).unref()
}

process.on("SIGINT", () => stopAll(0))
process.on("SIGTERM", () => stopAll(0))

console.log("Starting Job Orchestrator local workers:")
for (const service of services) {
  console.log(`  - ${service.name}: ${service.command} ${service.args.join(" ")}`)
}
console.log("")

for (const service of services) {
  start(service)
}
