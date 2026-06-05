# BotifyTrades Release Pipeline Setup

## Architecture Overview

```
┌─────────────┐     push      ┌──────────────────────┐
│   Replit    │ ────────────> │  BotifyTradesv2      │
│  (develop)  │               │  (private - source)  │
└─────────────┘               └──────────────────────┘
                                        │
                                        │ release.sh triggers
                                        │ repository_dispatch
                                        ▼
                              ┌──────────────────────┐
                              │  BotifyTrades        │
                              │  (public - builds)   │
                              │                      │
                              │  ┌────────────────┐  │
                              │  │ GitHub Actions │  │
                              │  │ - Build Win    │  │
                              │  │ - Build Linux  │  │
                              │  │ - Create Release│ │
                              │  └────────────────┘  │
                              └──────────────────────┘
```

## One-Time Setup Steps

### Step 1: Create GitHub Personal Access Token (PAT)

1. Go to: https://github.com/settings/tokens?type=beta
2. Click **"Generate new token"**
3. Name: `BotifyTrades Release Automation`
4. Expiration: No expiration (or 1 year)
5. Repository access: **Only select repositories**
   - Select: `DiscordTrader/BotifyTradesv2`
   - Select: `DiscordTrader/BotifyTrades`
6. Permissions:
   - **Repository permissions:**
     - Contents: Read and write
     - Actions: Read and write
7. Click **"Generate token"**
8. **COPY THE TOKEN** (you won't see it again!)

### Step 2: Add Token to GitHub Secrets (Public Repo)

1. Go to: https://github.com/DiscordTrader/BotifyTrades/settings/secrets/actions
2. Click **"New repository secret"**
3. Name: `PRIVATE_REPO_TOKEN`
4. Value: Paste the PAT from Step 1
5. Click **"Add secret"**

### Step 3: Add Token to Replit Secrets

1. In Replit, go to **Secrets** (lock icon in sidebar)
2. Add new secret:
   - Key: `RELEASE_TOKEN`
   - Value: Paste the same PAT from Step 1
3. Save

### Step 4: Add Workflow to Public Repo

1. Go to: https://github.com/DiscordTrader/BotifyTrades
2. Create file: `.github/workflows/build-release.yml`
3. Copy contents from: `packaging/docs/PUBLIC_REPO_WORKFLOW.yml`
4. Commit the file

## Usage

### Release a New Version

From Replit shell:
```bash
./scripts/release.sh 3.2.1
```

This will:
1. Update `upgrade/version.py` with version and date
2. Commit and push to BotifyTradesv2 (private)
3. Trigger the build workflow on BotifyTrades (public)
4. Builds are created and attached to a new GitHub release

### Manual Trigger (if needed)

If the automatic trigger fails:
1. Go to: https://github.com/DiscordTrader/BotifyTrades/actions
2. Select "Build and Release" workflow
3. Click "Run workflow"
4. Enter the version number (e.g., `3.2.1`)
5. Click "Run workflow"

## Troubleshooting

### "RELEASE_TOKEN not set"
- Add the PAT to Replit Secrets as `RELEASE_TOKEN`

### "Failed to trigger workflow (HTTP 404)"
- Verify the workflow file exists in the public repo
- Check that the PAT has correct repository access

### "Failed to trigger workflow (HTTP 403)"
- Check that the PAT has "Actions: Read and write" permission

### Build fails with "Could not checkout private repo"
- Verify `PRIVATE_REPO_TOKEN` secret is set in the public repo
- Check that the PAT has access to the private repo

## Security Notes

- The PAT is stored securely in GitHub Secrets (encrypted)
- The PAT is stored in Replit Secrets (encrypted)
- Never commit the PAT to any repository
- Regenerate the PAT if compromised
