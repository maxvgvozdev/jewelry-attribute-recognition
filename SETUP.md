# Local quickstart — Jewelry Attribute Recognition agent

## Already cloned from GitHub
You have the repo for the jewelry recognition agent. These steps apply on any Windows computer.

## Prerequisites
- Windows 10+
- Git (with Git LFS installed)
- Python 3.9+ (Python 3.11 recommended)
- Hermes Agent CLI on PATH

Verify tools:
```bash
git --version
git lfs version
python --version
hermes --version
```

## Install
1. Clone the repo to a local folder, e.g.:
```bash
git clone https://github.com/<your-username>/jewelry-attribute-recognition.git
cd jewelry-attribute-recognition
```

2. Pull LFS assets if needed:
```bash
git lfs pull
```

### Windows PowerShell note
If you see LF/CRLF warnings, they are non-blocking. You can disable this warning with:
```powershell
git config --global core.autocrlf true
```

## Hermes skill import
Copy the skill folder into your Hermes skills directory. Typical Windows profile path:
```powershell
Copy-Item -Recurse . "<$HOME>\AppData\Local\hermes\skills\data-science\jewelry-attribute-recognition"
```

You do not need to restart Hermes after importing the skill. Skills are loaded dynamically.

## Environment variables — do this on every machine
Set the Firecrawl API key for your account. This secret is NOT stored in Git.

### PowerShell
```powershell
$env:FIRECRAWL_API_KEY="your-api-key"
# make persistent for current user
[System.Environment]::SetEnvironmentVariable('FIRECRAWL_API_KEY','your-api-key','User')
```

### Command Prompt
```cmd
setx FIRECRAWL_API_KEY "your-api-key"
```

## Verify setup
From the Hermes skill folder:
```bash
python scripts/firecrawl_proxy.py search "site:brilliantearth.com morganite ring"
```

A printed JSON or error response means the script is working.

## Save token: optional convenience
If you use HTTPS with GitHub, cache credentials once:
```bash
git config --global credential.helper manager
```
Push/pull will not prompt again until credentials change or expire.

## Troubleshooting
- `Permission denied (publickey)`: switch to HTTPS remote or load SSH key.
- `error 400` on push: you used `<your-username>` as placeholder. Replace with your real GitHub username in `git remote set-url origin ...`.
- LFS showing placeholder files: run `git lfs pull` from the repo folder.
- Command `hermes` not found on another computer: install or symlink Hermes before importing the skill.
