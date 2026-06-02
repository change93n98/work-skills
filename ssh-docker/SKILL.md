---
name: ssh-docker
description: Run remote compile, test, profiling, and debug tasks through SSH plus docker exec. Prompts for target node (IP or hostname from ~/.ssh/config) and Docker container name on invocation. Keeps code edits local and synced to remote.
---

# SSH Docker Remote Workflow

## Execution Contract

Follow this rule for all downstream remote skills:

- Edit code only in the local repository.
- Sync local changes to remote using `.vscode/sftp.json` (`uploadOnSave: true`) or explicit upload commands.
- Execute remote work only with `ssh ... "docker exec ... sh -lc '<cmd>'"`.
- Avoid direct remote-host compilation and testing outside Docker unless explicitly requested.

## On Invocation: Gather Connection Parameters

When this skill is invoked, FIRST ask the user for the target node and container. Use this approach:

### Step 1: Ask for Target Node

Ask the user: "Which node do you want to connect to? You can provide:"
- A hostname alias from your `~/.ssh/config` (e.g., `gpu-server1`, `dev-node`)
- A direct IP address (e.g., `10.17.176.13`)
- A full SSH target (e.g., `user@host:port`)

### Step 2: Resolve Node Details

If user provides a hostname alias, look it up in `~/.ssh/config`:

```powershell
# Parse ssh config for the given host
$HostName = "<user_provided_hostname>"
$SshConfig = Get-Content "$env:USERPROFILE\.ssh\config" -Raw
$Pattern = "(?ms)Host\s+$HostName\s*\n(.*?)(?=\nHost\s|\z)"
if ($SshConfig -match $Pattern) {
    $HostBlock = $Matches[1]
    $SSH_HOST = if ($HostBlock -match "HostName\s+(.+)") { $Matches[1].Trim() } else { $HostName }
    $SSH_USER = if ($HostBlock -match "User\s+(.+)") { $Matches[1].Trim() } else { $env:USERNAME }
    $SSH_PORT = if ($HostBlock -match "Port\s+(.+)") { $Matches[1].Trim() } else { "22" }
    $SSH_KEY = if ($HostBlock -match "IdentityFile\s+(.+)") { $Matches[1].Trim() -replace '~', $env:USERPROFILE } else { $null }
} else {
    Write-Host "Host '$HostName' not found in ~/.ssh/config. Using it as direct hostname."
    $SSH_HOST = $HostName
    $SSH_USER = $env:USERNAME
    $SSH_PORT = "22"
    $SSH_KEY = $null
}
$SSH_TARGET = "$SSH_USER@$SSH_HOST"
```

If user provides an IP directly:
- `SSH_HOST` = the IP
- `SSH_USER` = ask or default to current Windows username
- `SSH_PORT` = ask or default to `22`
- `SSH_KEY` = ask or default to `~/.ssh/id_rsa`

### Step 3: Ask for Docker Container Name

Ask the user: "What is the Docker container name on this node?"
- Example: `megamoe`, `dev-container`, `ml-training`

### Step 4: Ask for Workspace Paths (Optional)

Ask the user for:
- Host workspace root (default: auto-detect from container mounts)
- Container workspace (default: `/workspace`)

Then derive:
- `REMOTE_PATH` = host path to project
- `CONTAINER_REPO` = container path to project

## Parameters Summary

After gathering, you should have:

- `SSH_HOST`: resolved from user input or ssh config
- `SSH_USER`: resolved from user input or ssh config
- `SSH_PORT`: resolved from user input or ssh config (default: 22)
- `SSH_KEY`: resolved from user input or ssh config (optional)
- `SSH_TARGET`: `$SSH_USER@$SSH_HOST`
- `DOCKER_NAME`: user-provided container name
- `REMOTE_PATH`: host path to project
- `CONTAINER_WORKSPACE`: container workspace root (default: `/workspace`)
- `CONTAINER_REPO`: `$CONTAINER_WORKSPACE/<project_folder>`

## Windows SSH Reliability Notes

On Windows, local OpenSSH config or ACLs can break authentication before the remote host is even reached.

- Prefer `ssh -F NUL ...` and `scp -F NUL ...` when you want to ignore local `~/.ssh/config`.
- If OpenSSH reports bad permissions on `~/.ssh/config`, either fix the ACLs or bypass the config with `-F NUL`.
- If OpenSSH reports bad permissions on the private key, create a temporary copy with restricted ACLs and use that copy for this session.

Example temporary-key workflow:

```powershell
if ($SSH_KEY) {
    $SSH_KEY_SRC = $SSH_KEY
    $SSH_KEY_TEMP = Join-Path $env:TEMP "ssh_docker_key"
    Copy-Item -LiteralPath $SSH_KEY_SRC -Destination $SSH_KEY_TEMP -Force
    icacls $SSH_KEY_TEMP /inheritance:r /grant:r "$((whoami)):F"
    $SSH_KEY = $SSH_KEY_TEMP
}
```

## Quick Verification Workflow

1. Verify SSH login and host identity.

```powershell
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "hostname && whoami"
```

2. Verify target container exists and is running.

```powershell
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "docker ps --format 'table {{.Names}}\t{{.Status}}' | sed -n '1,20p'"
```

If the expected container is missing from `docker ps`, check all containers:

```powershell
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "docker ps -a --filter name=$DOCKER_NAME --format 'table {{.Names}}\t{{.Status}}'"
```

3. Verify host/container mount metadata and workspace mapping in container.

```powershell
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "docker inspect $DOCKER_NAME --format '{{json .Mounts}}'"
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "docker exec $DOCKER_NAME sh -lc 'pwd && ls -la $CONTAINER_WORKSPACE'"
```

4. Check GPU/DCU/ROCm status, memory usage, and hardware information in container.

```powershell
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "docker exec $DOCKER_NAME sh -lc 'hy-smi || rocm-smi --showuse --showmemuse || rocm-smi || /opt/dtk/bin/rocm-smi || true'"
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "docker exec $DOCKER_NAME sh -lc '(rocninfo || rocminfo || /opt/dtk/bin/rocminfo) 2>/dev/null | egrep \"Name:|Marketing Name:|Vendor Name:|Device Type:|Compute Unit:|SIMDs per CU:|Wavefront Size:|ISA\" || true'"
```

Choose a device with low or zero compute and memory use, then use `HIP_VISIBLE_DEVICES=` to pin to that device.

5. Check Python package inventory in container.

```powershell
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "docker exec $DOCKER_NAME sh -lc 'cd $CONTAINER_REPO && pip3 list'"
```

## Compile, Test, Debug Templates

Run all project validation through the same remote execution pattern:

```powershell
# Compile check
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "docker exec $DOCKER_NAME sh -lc 'cd $CONTAINER_REPO && python3 -m compileall .'"

# Targeted tests
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "docker exec $DOCKER_NAME sh -lc 'cd $CONTAINER_REPO && pytest -q <path/to/test.py>'"

# Debug command (example)
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "docker exec $DOCKER_NAME sh -lc 'cd $CONTAINER_REPO && python3 <your_script.py>'"

# HIP/DTK sample compile + run (example)
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "docker exec $DOCKER_NAME sh -lc 'cd $CONTAINER_REPO && /opt/dtk/bin/hipcc -O2 hip_vector_add.cpp -o hip_vector_add && HIP_VISIBLE_DEVICES=<device_id> ./hip_vector_add'"
```

For GPU pinning, prefix the inner command with environment variables:

```powershell
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "docker exec $DOCKER_NAME sh -lc 'cd $CONTAINER_REPO && HIP_VISIBLE_DEVICES=<device_id> PYTHONPATH=. pytest -q <gpu_test.py>'"
```

## Sync Guidance

- Keep `.vscode/sftp.json` `uploadOnSave` enabled.
- Save locally first, then execute remotely.
- Before the first upload, ensure the remote target directory exists:

```powershell
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "mkdir -p $REMOTE_PATH"
```

- After the first upload, verify the host path and container path both see the project:

```powershell
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "test -d $REMOTE_PATH && echo remote_repo_ok=$REMOTE_PATH"
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "docker exec $DOCKER_NAME sh -lc 'test -d $CONTAINER_REPO && echo container_repo_ok=$CONTAINER_REPO'"
```

- If a file does not appear remotely in time, upload it explicitly:

```powershell
scp -F NUL -P $SSH_PORT -i $SSH_KEY <local_file> "${SSH_TARGET}:$REMOTE_PATH/<relative_target>"
```

## Sync Back Container Outputs

Files generated inside Docker are usually owned by `root` on the host bind mount.

- `root:root` files with mode `0644` and directories with mode `0755` can be pulled by `scp` or SFTP.
- `root:root` files with mode `0600` or directories with mode `0700` cannot be pulled; expect `Permission denied`.
- Prefer fixing ownership in Docker before syncing outputs back:

```powershell
$HOST_UID_GID = ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "stat -c '%u:%g' $REMOTE_PATH"
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "docker exec $DOCKER_NAME sh -lc 'chown -R $HOST_UID_GID $CONTAINER_REPO/<output_dir>'"
scp -F NUL -P $SSH_PORT -i $SSH_KEY -r "${SSH_TARGET}:$REMOTE_PATH/<output_dir>" <local_target_dir>
```

## Failure Handling

- If `docker exec` fails with "container not running", start it and rerun:

```powershell
ssh -F NUL $SSH_TARGET -p $SSH_PORT -i $SSH_KEY "docker start $DOCKER_NAME"
```

- If authentication fails before reaching the remote shell, check for local OpenSSH ACL problems and switch to `-F NUL` plus a temporary key copy.
- If `rocm-smi` is unavailable in container, run it on host once to confirm driver state.
- If package or import checks fail, treat environment mismatch separately from code regressions.
