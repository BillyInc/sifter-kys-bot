module.exports = {
  apps: [{
    name: 'sifter-backend',
    cwd: __dirname,
    script: '.venv/bin/gunicorn',
    args: '--bind 0.0.0.0:5000 --workers 2 --timeout 120 app:app',
    interpreter: 'none',
    env: {
      PORT: 5000
    },
    // Restart settings
    autorestart: true,
    watch: false,
    max_memory_restart: '500M',
    // Logging
    error_file: 'logs/pm2-error.log',
    out_file: 'logs/pm2-out.log',
    merge_logs: true,
    log_date_format: 'YYYY-MM-DD HH:mm:ss Z'
  }]
}
