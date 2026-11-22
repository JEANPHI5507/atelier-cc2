# Docker Installation Guide

[\u2190 Back to the README](../../README.md) \u00b7 \ud83c\uddeb\ud83c\uddf7 [Fran\u00e7ais](../docker.md)

## Overview

This guide explains how to run **Atelier CC2** using Docker. This is the recommended method for:
- **Windows users** (via WSL2)
- **Mac users** (via Docker Desktop)
- **Linux users** who want an isolated environment
- **Server deployments**

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) installed
- [Docker Compose](https://docs.docker.com/compose/install/) (optional, for multi-container setups)
- At least **4GB of RAM** (recommended: 8GB for full functionality)
- **2GB of disk space** (for OrcaSlicer and dependencies)

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/JEANPHI5507/atelier-cc2.git
cd atelier-cc2
```

### 2. Build the Docker Image

```bash
# Build the image (takes ~5-10 minutes)
docker build -t atelier-cc2 .
```

### 3. Run with Simulator (No Printer Required)

```bash
# Run the simulator (demo mode)
docker run -it --rm \
  -p 8788:8788 \
  -v $(pwd)/demo:/home/appuser/app/demo \
  atelier-cc2
```

Then open your browser to: **http://localhost:8788/lab/**

### 4. Run with Real CC2 Printer

```bash
# Run with your CC2 (replace IP and CODE with your printer's values)
docker run -it --rm \
  -p 8787:8787 \
  -v $(pwd)/config.toml:/home/appuser/app/config.toml:ro \
  -v $(pwd)/models:/home/appuser/app/models \
  -v $(pwd)/demo:/home/appuser/app/demo \
  atelier-cc2 \
  --control dash --ip 192.168.1.100 --code 123456
```

Then open your browser to: **http://localhost:8787/lab/**

## Using Docker Compose

### 1. Start the Simulator

```bash
# Start with simulator
docker-compose up -d

# View logs
docker-compose logs -f atelier-cc2

# Stop
docker-compose down
```

Access the interface at: **http://localhost:8788/lab/**

### 2. Configure for Real Printer

Edit the `docker-compose.yml` file and update the command:

```yaml
services:
  atelier-cc2:
    # ... other configurations ...
    command: ["--control", "dash", "--ip", "YOUR_PRINTER_IP", "--code", "YOUR_ACCESS_CODE"]
```

Then restart:

```bash
docker-compose down && docker-compose up -d
```

## Volume Persistence

The following directories are persisted by default:

| Local Directory | Container Path | Purpose |
|-----------------|----------------|---------|
| `./config.toml` | `/home/appuser/app/config.toml` | Configuration file |
| `./models` | `/home/appuser/app/models` | 3D models library |
| `./demo` | `/home/appuser/app/demo` | Simulator data |
| `./gallery` | `/home/appuser/app/gallery` | Print history and photos |

## OrcaSlicer Installation

OrcaSlicer is automatically installed on first run. However, you can also install it manually:

```bash
# Enter the container
docker run -it --rm \
  -v $(pwd):/home/appuser/app \
  atelier-cc2 bash

# Inside the container, run:
cd /home/appuser/app
make slicer
```

## AI Model Installation (Optional)

To enable the spaghetti detection AI:

```bash
# Enter the container
docker run -it --rm \
  -v $(pwd):/home/appuser/app \
  atelier-cc2 bash

# Inside the container, run:
cd /home/appuser/app
make ia
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PYTHONUNBUFFERED` | Disable Python output buffering | `1` |
| `PYTHONDONTWRITEBYTECODE` | Disable Python bytecode writing | `1` |

## Ports

| Port | Service | Description |
|------|---------|-------------|
| 8787 | Atelier CC2 (Control Mode) | With real printer |
| 8788 | Atelier CC2 (Simulator Mode) | Demo mode |

## Troubleshooting

### "Permission Denied" Errors

Make sure the local directories exist and have the correct permissions:

```bash
mkdir -p models demo gallery
chmod -R 777 models demo gallery
```

### Docker Build Fails

Try cleaning the Docker cache:

```bash
docker system prune -a
docker build --no-cache -t atelier-cc2 .
```

### OrcaSlicer Not Found

Make sure OrcaSlicer is installed:

```bash
docker run -it --rm atelier-cc2 make slicer
```

### Port Already in Use

Check which process is using the port:

```bash
# On Linux
sudo lsof -i :8788

# On Windows
netstat -ano | findstr 8788
```

Then either stop the conflicting process or use a different port by modifying the `docker run` command.

## Windows (WSL2) Specific

### 1. Install WSL2

```powershell
# Enable WSL
wsl --install

# Set WSL2 as default
wsl --set-default-version 2
```

### 2. Install Docker Desktop

Download and install [Docker Desktop for Windows](https://docs.docker.com/docker-for-windows/install/)

### 3. Enable WSL2 Integration

1. Open Docker Desktop
2. Go to **Settings > Resources > WSL Integration**
3. Enable integration with your WSL2 distribution

### 4. Run Atelier CC2

```bash
# In WSL2 terminal
git clone https://github.com/JEANPHI5507/atelier-cc2.git
cd atelier-cc2
docker build -t atelier-cc2 .
docker run -it --rm -p 8788:8788 atelier-cc2
```

## macOS Specific

### 1. Install Docker Desktop

Download and install [Docker Desktop for Mac](https://docs.docker.com/docker-for-mac/install/)

### 2. Increase Docker Resources

1. Open Docker Desktop
2. Go to **Preferences > Resources**
3. Increase memory to at least **4GB** (recommended: 8GB)
4. Increase disk space to at least **20GB**

### 3. Run Atelier CC2

```bash
git clone https://github.com/JEANPHI5507/atelier-cc2.git
cd atelier-cc2
docker build -t atelier-cc2 .
docker run -it --rm -p 8788:8788 atelier-cc2
```

## Performance Tips

1. **Use Docker cache**: The first build takes longer, but subsequent builds are faster.
2. **Limit OrcaSlicer threads**: If you have limited CPU, you can limit OrcaSlicer threads:
   ```bash
   docker run -it --rm -e OMP_NUM_THREADS=2 atelier-cc2
   ```
3. **Use a separate volume for OrcaSlicer**: To avoid rebuilding OrcaSlicer:
   ```bash
   docker run -it --rm \
     -v orcaslicer_cache:/home/appuser/app/OrcaSlicer \
     atelier-cc2
   ```

## Updating

To update to the latest version:

```bash
# Pull the latest changes
git pull origin main

# Rebuild the image
docker build -t atelier-cc2 . --no-cache

# Restart the container
docker-compose down && docker-compose up -d
```

## Uninstalling

To completely remove Atelier CC2:

```bash
# Stop and remove containers
docker-compose down

# Remove the image
docker rmi atelier-cc2

# Remove volumes (WARNING: This will delete all your data!)
docker volume prune

# Remove local files
rm -rf atelier-cc2
```

## Security Considerations

1. **Run as non-root**: The Dockerfile creates a non-root user (`appuser`) for security.
2. **Limit permissions**: Only expose the necessary ports (8787, 8788).
3. **Use read-only volumes**: For configuration files, use read-only mounts:
   ```bash
   -v $(pwd)/config.toml:/home/appuser/app/config.toml:ro
   ```
4. **Keep Docker updated**: Regularly update Docker to get the latest security patches.

## Advanced Configuration

### Custom Dockerfile

You can customize the Dockerfile to:
- Add additional dependencies
- Change the Python version
- Modify the entrypoint script

### Multiple Containers

For advanced setups (e.g., separate camera service), you can extend the `docker-compose.yml`:

```yaml
version: '3.8'

services:
  atelier-cc2:
    build: .
    ports:
      - "8787:8787"
    volumes:
      - ./models:/home/appuser/app/models
    
  camera:
    image: aler9/rtsp-simple-server
    ports:
      - "8554:8554"
    devices:
      - "/dev/video0:/dev/video0"
```

## License

This guide is part of the **Atelier CC2** project, licensed under **MIT**. See [LICENSE](../../LICENSE) for details.
