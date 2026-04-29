# Claude Git Workflow

## Overview
This document defines the standard Git workflow Claude must follow when working on this repository.

---

## Core Rules

1. Always create a branch from `main`
2. Always ask for the branch name
3. Always ask for the issue or feature context
4. Implement the requested change
5. Commit, push, and create a pull request

---

## Mandatory Constraints

- Always start from latest `main`
- Never branch from another feature branch
- Never skip asking for branch name
- Never skip asking for context
- Keep changes minimal and focused
- Avoid unnecessary refactoring
- Always create a PR after changes

---

## Step-by-Step Workflow

### Step 1: Sync Main Branch
```bash
git checkout main
git pull origin main
```

### Step 2: Ask for Branch Name
> What branch name should I use?

Wait for user input before proceeding.

### Step 3: Create Branch
```bash
git checkout -b <branch-name>
```

### Step 4: Ask for Context
> Please share the issue or feature details.

Wait for user input before proceeding.

### Step 5: Implement Changes
- Review codebase
- Understand requirement
- Apply fix or feature
- Keep implementation clean and minimal

### Step 6: Commit Changes
```bash
git add <files>
git commit -m "<type>: <short summary>"
```

Examples:
- `fix: resolve login issue`
- `feat: add new API endpoint`

### Step 7: Push Branch
```bash
git push origin <branch-name>
```

### Step 8: Create Pull Request
Create a PR targeting `main`.

---

## Pull Request Format

### Title
```
<type>: <short summary>
```

### Body
```md
## Summary
Brief explanation of changes

## Context
What issue or feature this addresses

## Changes Made
- Change 1
- Change 2

## Notes
Additional details if any
```

---

## Execution Behavior

Claude must ALWAYS follow this sequence:

1. Checkout main
2. Pull latest main
3. Ask for branch name
4. Create branch
5. Ask for context
6. Implement changes
7. Commit
8. Push
9. Create PR

Never skip asking steps. Never assume context. Always follow process strictly.
