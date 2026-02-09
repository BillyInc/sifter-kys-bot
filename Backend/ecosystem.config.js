module.exports = {
  apps: [
    {
      name: 'sifter-backend',
      cwd: __dirname,  // Stay in backend/ folder
      script: 'app.py',
      interpreter: '../.venv/Scripts/python.exe',
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
      script: 'rq',
      args: 'worker -w rq.SimpleWorker',
      interpreter: '../.venv/Scripts/python.exe',
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
      cwd: __dirname + '/backend',
      script: 'python',
      args: '-m services.wallet_monitor',  // Run as module
      interpreter: '../.venv/Scripts/python.exe',  // Windows
      // interpreter: '../.venv/bin/python',  // Linux
      autorestart: true,
      max_memory_restart: '500M',
      error_file: 'logs/wallet-monitor-error.log',
      out_file: 'logs/wallet-monitor-out.log'
    },



  ]
}