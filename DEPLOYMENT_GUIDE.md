# 🚀 SarkariSahayata — Professional AWS Deployment Guide

This comprehensive, step-by-step guide walks you through deploying the **SarkariSahayata** Flask portal to an **AWS EC2 (Ubuntu 24.04)** server using **Nginx**, **Gunicorn**, and your existing **Aiven Cloud MySQL** database.

---

## 🏛️ Architecture Overview

```
                      [ Client / Browser ]
                               │
                               │ HTTPS (Port 443) / HTTP (Port 80)
                               ▼
            ┌─────────────────────────────────────────┐
            │             AWS EC2 Instance            │
            │                                         │
            │  ┌───────────────────────────────────┐  │
            │  │  Nginx Web Server (Reverse Proxy) │  │
            │  │  - Serves static assets (CSS/JS)   │  │
            │  │  - Terminates SSL/TLS certificates │  │
            │  └─────────────────┬─────────────────┘  │
            │                    │ Port 5000          │
            │                    ▼                    │
            │  ┌───────────────────────────────────┐  │
            │  │  Gunicorn (WSGI Application Server)│ │
            │  │  - Multi-worker daemon            │  │
            │  │  - Managed via Systemd service    │  │
            │  └─────────────────┬─────────────────┘  │
            │                    │                    │
            │  ┌─────────────────▼─────────────────┐  │
            │  │  Flask Application (flaskr)       │  │
            │  └───────────────────────────────────┘  │
            └────────────────────┬────────────────────┘
                                 │
                                 │ Secure SSL connection (Port 19881)
                                 ▼
                   [ Aiven Cloud MySQL Database ]
                    - 32 Government schemes
                    - User profiles & admin logs
```

---

## 📋 Prerequisites

Before starting, ensure you have:
1. An active **AWS Account** ([aws.amazon.com](https://aws.amazon.com/)).
2. Your **Aiven Cloud MySQL** credentials (already configured in `.env`).
3. **PowerShell** or terminal on your computer to connect via SSH.

---

## Step 1: Launch an AWS EC2 Instance

1. Log into your [AWS Management Console](https://console.aws.amazon.com/).
2. In the top search bar, type **EC2** and click on **EC2**.
3. Click the orange **Launch instance** button.
4. Fill in the instance configuration:
   - **Name**: `sarkarisahayata-server`
   - **OS (AMI)**: Select **Ubuntu** $\rightarrow$ **Ubuntu Server 24.04 LTS (HVM)** *(Free Tier eligible)*.
   - **Instance type**: `t2.micro` (or `t3.micro` if in regions like Mumbai).
   - **Key pair (login)**:
     - Click **Create new key pair**.
     - Key pair name: `sarkari-key`.
     - Key pair type: **RSA**.
     - Private key file format: **`.pem`**.
     - Click **Create key pair** (this will download `sarkari-key.pem` to your PC. Store it safely in `Downloads`).
   - **Network settings (Firewall / Security Group)**:
     - ✅ Check **Allow SSH traffic from Anywhere (0.0.0.0/0)**.
     - ✅ Check **Allow HTTP traffic from the internet (port 80)**.
     - ✅ Check **Allow HTTPS traffic from the internet (port 443)**.
5. Click **Launch instance** (bottom right).
6. Click **Instances** in the sidebar. Once the status shows **Running**, copy your **Public IPv4 address** (e.g., `13.233.45.67`).

---

## Step 2: Connect to Your EC2 Server via SSH

Open **PowerShell** on your Windows computer and execute:

```powershell
# Navigate to the folder containing your downloaded key
cd C:\Users\Sahil\Downloads

# Connect to the EC2 server (replace with your real EC2 Public IP)
ssh -i "sarkari-key.pem" ubuntu@YOUR_EC2_PUBLIC_IP
```

> **Note:** If prompted with `Are you sure you want to continue connecting (yes/no)?`, type `yes` and hit **Enter**.

---

## Step 3: Install Required Server Packages

Run these commands inside your EC2 SSH session:

```bash
# 1. Update system package repository
sudo apt update && sudo apt upgrade -y

# 2. Install Python 3, venv, MySQL client development headers, Nginx, and Git
sudo apt install -y python3-pip python3-venv git default-libmysqlclient-dev pkg-config build-essential nginx curl
```

---

## Step 4: Clone Codebase & Setup Python Environment

Still inside your EC2 terminal:

```bash
# 1. Navigate to /var/www and clone the project
cd /var/www
sudo git clone https://github.com/Gtg727/SarkariSahayata.git
sudo chown -R ubuntu:ubuntu /var/www/SarkariSahayata
cd SarkariSahayata

# 2. Create and activate a clean Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Upgrade pip and install all project dependencies
pip install --upgrade pip
pip install -r requirements.txt gunicorn

# 4. Create your production environment file (.env)
nano .env
```

Paste your exact configuration into `nano`:

```ini
SECRET_KEY=dev-sarkari-sahayata-secret-key-2026

# Mail Configuration
MAIL_DEFAULT_SENDER=noreply@flask.com
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=465
MAIL_USE_TLS=False
MAIL_USE_SSL=True
MAIL_DEBUG=False
MAIL_USERNAME=your_email@gmail.com
MAIL_PASSWORD=your_email_app_password

# Aiven Cloud MySQL Database Configuration
MYSQL_HOST=mysql-3728ff7c-sarkari-sahayta-14.i.aivencloud.com
MYSQL_USER=avnadmin
MYSQL_PASSWORD=your_aiven_mysql_password
MYSQL_DB=defaultdb
MYSQL_PORT=19881

# Master Administrator Credentials
MASTER_USER=sarkariadmin1
MASTER_PASSWORD=your_master_admin_password

# Flask Environment
FLASK_APP=flaskr
FLASK_DEBUG=0
```

- Press `Ctrl + O`, then press `Enter` to save.
- Press `Ctrl + X` to exit `nano`.

Test Gunicorn briefly to ensure it loads properly:
```bash
gunicorn --bind 0.0.0.0:5000 wsgi:app
```
*(Press `Ctrl + C` after verifying it boots without errors).*

---

## Step 5: Configure Gunicorn as a Persistent Background Service

This step ensures your application runs 24/7, restarts automatically on reboot, and recovers if a worker crashes.

```bash
sudo nano /etc/systemd/system/sarkarisahayata.service
```

Paste the following service definition:

```ini
[Unit]
Description=Gunicorn daemon for SarkariSahayata Flask Application
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/var/www/SarkariSahayata
EnvironmentFile=/var/www/SarkariSahayata/.env
ExecStart=/var/www/SarkariSahayata/.venv/bin/gunicorn --workers 3 --bind 127.0.0.1:5000 wsgi:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Save and exit (`Ctrl + O`, `Enter`, `Ctrl + X`).

Now enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl start sarkarisahayata
sudo systemctl enable sarkarisahayata

# Check service status:
sudo systemctl status sarkarisahayata
```
*(You will see a green `active (running)` status. Press `q` to return to terminal).*

---

## Step 6: Configure Nginx as the Production Reverse Proxy

Nginx will receive incoming public web requests, serve static images and stylesheets directly for maximum speed, and pass application requests to Gunicorn.

```bash
sudo nano /etc/nginx/sites-available/sarkarisahayata
```

Paste this configuration (replace `YOUR_EC2_PUBLIC_IP` with your actual EC2 public IP):

```nginx
server {
    listen 80;
    server_name YOUR_EC2_PUBLIC_IP;

    client_max_body_size 16M;

    # Serve static files directly
    location /static/ {
        alias /var/www/SarkariSahayata/flaskr/static/;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }

    # Forward all dynamic traffic to Gunicorn
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Save and exit (`Ctrl + O`, `Enter`, `Ctrl + X`).

Enable the site and restart Nginx:

```bash
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -s /etc/nginx/sites-available/sarkarisahayata /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

🎉 **Test in Browser**: Open `http://YOUR_EC2_PUBLIC_IP/` in any web browser. Your portal is now live on AWS!

---

## Step 7: (Optional) Custom Domain & Free SSL (HTTPS)

When you are ready to link a custom domain (e.g. `sarkarisahayata.in`):

1. **DNS Record**: In your domain registrar (GoDaddy, Namecheap, Hostinger, etc.), add an **A Record**:
   - **Type**: `A`
   - **Name**: `@`
   - **Value**: `YOUR_EC2_PUBLIC_IP`
2. **Update Nginx**:
   ```bash
   sudo nano /etc/nginx/sites-available/sarkarisahayata
   # Change 'server_name YOUR_EC2_PUBLIC_IP;' to 'server_name yourdomain.com www.yourdomain.com;'
   sudo systemctl restart nginx
   ```
3. **Install Free SSL via Let's Encrypt**:
   ```bash
   sudo apt install -y certbot python3-certbot-nginx
   sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
   ```
   Certbot will automatically provision your SSL certificate and configure HTTPS redirection.

---

## 🛠️ Useful Management & Troubleshooting Commands

| Task | Command |
|---|---|
| **Restart Flask Application** | `sudo systemctl restart sarkarisahayata` |
| **View Live Application Logs** | `sudo journalctl -u sarkarisahayata -f` |
| **Restart Nginx** | `sudo systemctl restart nginx` |
| **Check Nginx Error Logs** | `sudo tail -f /var/log/nginx/error.log` |
| **Deploy Code Updates from Git** | `cd /var/www/SarkariSahayata && git pull && sudo systemctl restart sarkarisahayata` |
