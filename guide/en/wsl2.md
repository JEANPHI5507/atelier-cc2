# WSL2 Installation Guide for Windows

[\u2190 Back to the README](../../README.md) \u00b7 \ud83c\uddeb\ud83c\uddf7 [Fran\u00e7ais](../wsl2.md)

## Overview

This guide explains how to run **Atelier CC2** on **Windows 10/11** using **WSL2 (Windows Subsystem for Linux 2)**. This is the recommended method for Windows users.

## Prerequisites

- **Windows 10 version 2004 or later** (Build 19041 or higher)
- **Windows 11** (any version)
- **Administrator access** (for WSL2 installation)
- **At least 4GB of RAM** (recommended: 8GB)
- **20GB of free disk space** (for WSL2 and dependencies)

## Step 1: Enable WSL2

### Option A: Using PowerShell (Recommended)

Open **PowerShell as Administrator** and run:

```powershell
# Enable WSL2 and install Ubuntu (default distribution)
wsl --install

# Set WSL2 as the default version
wsl --set-default-version 2
```

### Option B: Manual Installation

1. **Enable Virtual Machine Platform** (if not already enabled):
   ```powershell
   dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
   ```

2. **Enable WSL**:
   ```powershell
   dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
   ```

3. **Restart your computer**

4. **Download and install WSL2 Linux kernel update**:
   - [Download from Microsoft](https://aka.ms/wsl2kernel)

5. **Set WSL2 as default**:
   ```powershell
   wsl --set-default-version 2
   ```

6. **Install a Linux distribution** (e.g., Ubuntu):
   - Open Microsoft Store
   - Search for "Ubuntu" and install it
   - Or use PowerShell:
     ```powershell
     wsl --install -d Ubuntu
     ```

## Step 2: Install Docker Desktop

1. **Download Docker Desktop for Windows**:
   - [Download from Docker](https://docs.docker.com/docker-for-windows/install/)

2. **Install Docker Desktop**:
   - Run the installer
   - Follow the installation steps

3. **Enable WSL2 Integration**:
   - Open Docker Desktop
   - Go to **Settings > Resources > WSL Integration**
   - Enable integration with your WSL2 distribution (e.g., Ubuntu)
   - Click **Apply & Restart**

## Step 3: Set Up WSL2 Environment

### Open WSL2 Terminal

1. Press **Win + R**, type `wsl` and press Enter
2. Or open **Ubuntu** from the Start Menu

### Update System

```bash
# Update package lists
sudo apt update && sudo apt upgrade -y

# Install basic dependencies
sudo apt install -y git curl wget build-essential python3-pip python3-venv
```

### Install uv (Python Package Manager)

```bash
# Install uv (recommended package manager for this project)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Add uv to PATH
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

## Step 4: Clone and Set Up Atelier CC2

```bash
# Clone the repository
git clone https://github.com/JEANPHI5507/atelier-cc2.git
cd atelier-cc2

# Install Python dependencies
uv sync

# Install OrcaSlicer
make slicer

# Optional: Install AI model for spaghetti detection
make ia
```

## Step 5: Run Atelier CC2

### Option A: Using Docker (Recommended)

```bash
# Build the Docker image
docker build -t atelier-cc2 .

# Run with simulator (demo mode)
docker run -it --rm -p 8788:8788 atelier-cc2

# Then open your browser to: http://localhost:8788/lab/
```

### Option B: Directly in WSL2

```bash
# Run with simulator (demo mode)
uv run cc2 simulateur

# Then open your browser to: http://localhost:8788/lab/

# Run with real CC2 (replace IP and CODE with your printer's values)
uv run cc2 --control dash --ip 192.168.1.100 --code 123456

# Then open your browser to: http://localhost:8787/lab/
```

## Step 6: Access from Windows Browser

When running Atelier CC2 in WSL2, you can access it from your Windows browser using:
- **http://localhost:8787/lab/** (for real printer)
- **http://localhost:8788/lab/** (for simulator)

This works because WSL2 automatically forwards localhost ports to the Windows host.

## Troubleshooting

### "WSL2 requires an update to its kernel component"

Download and install the latest WSL2 kernel update:
- [WSL2 Linux kernel update](https://aka.ms/wsl2kernel)

Then restart your computer.

### "Error: 0x80370102 The virtual machine could not be started"

1. Make sure **Virtual Machine Platform** is enabled:
   ```powershell
   dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
   ```

2. Make sure **Hyper-V** is enabled:
   ```powershell
   Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All
   ```

3. Restart your computer

### "Docker Desktop requires WSL2"

1. Make sure WSL2 is set as the default:
   ```powershell
   wsl --set-default-version 2
   ```

2. Restart Docker Desktop

### "Permission Denied" When Running Docker

Make sure your user is in the **docker** group:

```bash
# In WSL2
sudo usermod -aG docker $USER
newgrp docker
```

Then restart your WSL2 terminal.

### "No such file or directory" When Running make

Make sure you have **make** installed:

```bash
sudo apt install -y make
```

### "uv: command not found"

Make sure uv is in your PATH:

```bash
# Add to ~/.bashrc if not already there
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### Port Already in Use

Check which process is using the port:

```powershell
# On Windows
netstat -ano | findstr 8788
```

Then either stop the conflicting process or use a different port.

## Performance Tips

### Increase WSL2 Memory Limit

1. Create or edit `~/.wslconfig` in your **Windows user profile** (not in WSL2):

   ```ini
   [wsl2]
   memory=8GB    # Limits VM to 8 GB RAM
   processors=4  # Limits VM to 4 CPU cores
   swap=4GB      # Limits swap space to 4 GB
   ```

2. Restart WSL2:
   ```powershell
   wsl --shutdown
   ```

### Increase Docker Resources

1. Open Docker Desktop
2. Go to **Settings > Resources**
3. Increase **Memory** to at least 4GB (recommended: 8GB)
4. Increase **CPUs** to at least 2 (recommended: 4)
5. Click **Apply & Restart**

### Use a Separate Disk for WSL2

If you have a secondary drive, you can store WSL2 there:

1. Export your WSL2 distribution:
   ```powershell
   wsl --export Ubuntu ubuntu.tar
   ```

2. Move the file to your secondary drive:
   ```powershell
   move ubuntu.tar D:\wsl\ubuntu.tar
   ```

3. Import it back:
   ```powershell
   wsl --import Ubuntu D:\wsl\ubuntu ubuntu.tar --version 2
   ```

4. Set as default:
   ```powershell
   wsl --set-default Ubuntu
   ```

## Accessing Files from Windows

You can access your WSL2 files from Windows Explorer by navigating to:
```
\\wsl$\Ubuntu\home\<your-username>\atelier-cc2
```

## Updating

To update Atelier CC2:

```bash
# In WSL2
cd atelier-cc2
git pull origin main
uv sync
```

If using Docker:

```bash
# In WSL2
cd atelier-cc2
git pull origin main
docker build -t atelier-cc2 . --no-cache
```

## Uninstalling

To completely remove Atelier CC2 from WSL2:

```bash
# In WSL2
rm -rf atelier-cc2
```

To remove WSL2:

```powershell
# In PowerShell as Administrator
wsl --unregister Ubuntu
wsl --shutdown
```

## Security Considerations

1. **Keep WSL2 Updated**: Regularly update your WSL2 distribution:
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

2. **Use Strong Passwords**: Set a strong password for your WSL2 user

3. **Limit Docker Permissions**: Only expose necessary ports

4. **Use Firewall**: Make sure Windows Firewall is enabled

## License

This guide is part of the **Atelier CC2** project, licensed under **MIT**. See [LICENSE](../../LICENSE) for details.
