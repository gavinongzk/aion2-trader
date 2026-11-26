import { execFile } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

// `python -m aion2 compare` writes ../reports/compare.json; the app reads it from /compare.json.
const ROOT = path.resolve(import.meta.dirname, '..')
const DATA = path.join(ROOT, 'reports/compare.json')
const PREV_DATA = path.join(ROOT, 'reports/compare.prev.json') // copy of the run before the latest
const BOT_DATA = path.join(ROOT, 'reports/bot.json')
// what you hold, from the Sell view: [{key, name, qty, paid}]
const HOLDINGS = path.join(ROOT, 'reports/holdings.json')

// one compare at a time: a second click while one runs waits for the same run
let running: Promise<void> | null = null
function runCompare(): Promise<void> {
  running ??= new Promise<void>((resolve, reject) => {
    execFile(path.join(ROOT, '.venv/bin/python'), ['-m', 'aion2', 'compare'], { cwd: ROOT, timeout: 10 * 60_000, env: { ...process.env, PYTHON_COLORS: '0' } }, (err, _out, stderr) => {
      if (!err) return resolve()
      const last = stderr.trim().split('\n').at(-1)
      reject(new Error(last || err.message))
    })
  }).finally(() => (running = null))
  return running
}

function comparisonData(): Plugin {
  return {
    name: 'comparison-data',
    configureServer(server) {
      // the dashboard's refresh button: fetch fresh prices and rebuild compare.json
      server.middlewares.use('/refresh', (req, res) => {
        if (req.method !== 'POST') {
          res.statusCode = 405
          res.end()
          return
        }
        runCompare().then(
          () => res.end('ok'),
          (e: Error) => {
            res.statusCode = 500
            res.end(e.message)
          },
        )
      })
      // the Sell view's list of what you hold: read it, or replace it with a PUT of the whole list
      server.middlewares.use('/holdings.json', (req, res) => {
        if (req.method === 'PUT') {
          let body = ''
          req.on('data', (chunk) => (body += chunk))
          req.on('end', () => {
            try {
              const list = JSON.parse(body)
              if (!Array.isArray(list)) throw new Error('expected a list')
              fs.mkdirSync(path.dirname(HOLDINGS), { recursive: true })
              fs.writeFileSync(HOLDINGS, JSON.stringify(list, null, 2))
              res.end('ok')
            } catch (e) {
              res.statusCode = 400
              res.end((e as Error).message)
            }
          })
          return
        }
        res.setHeader('Content-Type', 'application/json')
        res.end(fs.existsSync(HOLDINGS) ? fs.readFileSync(HOLDINGS) : '[]')
      })
      server.middlewares.use('/compare.json', (_req, res) => {
        // the last run's data, or the previous good copy if it's missing
        const file = [DATA, PREV_DATA].find((f) => fs.existsSync(f))
        if (!file) {
          res.statusCode = 404
          res.end('run `python -m aion2 compare` first')
          return
        }
        res.setHeader('Content-Type', 'application/json')
        fs.createReadStream(file).pipe(res)
      })
    },
    generateBundle() {
      const data = [DATA, PREV_DATA].find((f) => fs.existsSync(f))
      if (data) this.emitFile({ type: 'asset', fileName: 'compare.json', source: fs.readFileSync(data) })
      // the slash-command function (../vercel) and the data it answers from (bot.json, from `python -m aion2 publish`)
      const fn = path.join(ROOT, 'vercel')
      this.emitFile({ type: 'asset', fileName: 'api/discord.py', source: fs.readFileSync(path.join(fn, 'api/discord.py')) })
      this.emitFile({ type: 'asset', fileName: 'requirements.txt', source: fs.readFileSync(path.join(fn, 'requirements.txt')) })
      if (fs.existsSync(BOT_DATA)) this.emitFile({ type: 'asset', fileName: 'bot.json', source: fs.readFileSync(BOT_DATA) })
      // deployed as built (see .github/workflows/refresh.yml): Vercel only installs the function's requirements
      this.emitFile({
        type: 'asset',
        fileName: 'vercel.json',
        source: JSON.stringify({ framework: null, functions: { 'api/discord.py': { includeFiles: 'bot.json', maxDuration: 10 } } }),
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), comparisonData()],
  publicDir: false,
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  build: {
    rolldownOptions: {
      // recharts is most of the bundle; keep it in its own cacheable chunk
      output: { codeSplitting: { groups: [{ name: 'charts', test: /node_modules[\\/](recharts|d3-|victory-vendor)/ }] } },
    },
  },
})
