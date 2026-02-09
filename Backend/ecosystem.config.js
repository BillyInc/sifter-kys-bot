const path = require('path');

// Detect OS for interpreter path
const isWindows = process.platform === 'win32';
const pythonInterpreter = isWindows
  ? path.join(__dirname, '.venv', 'Scripts', 'python.exe')
  : path.join(__dirname, '.venv', 'bin', 'python');

module.exports = {
  apps: [
    {
      name: 'sifter-backend',
      cwd: __dirname,
      script: 'app.py',
      interpreter: pythonInterpreter,
      env: {
        PORT: 5000
      },
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      error_file: 'logs/pm2-error.log',
      out_file: 'logs/pm2-out.log',
      merge_logs: true,
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z'
    },
    {
      name: 'rq-worker',
      cwd: __dirname,
      script: pythonInterpreter,
      args: '-m rq.cli worker -w rq.SimpleWorker',
      instances: 5,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      error_file: 'logs/rq-worker-error.log',
      out_file: 'logs/rq-worker-out.log',
      merge_logs: true,
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z'
    },
    {
      name: 'wallet-monitor',
      cwd: __dirname,
      script: pythonInterpreter,
      args: '-m services.wallet_monitor',
      autorestart: true,
      max_memory_restart: '500M',
      error_file: 'logs/wallet-monitor-error.log',
      out_file: 'logs/wallet-monitor-out.log',
      merge_logs: true,
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z'
    }
  ]
}