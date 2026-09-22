#!/usr/bin/env bash
# gpu-container-lookup.sh — 查询远程节点上"哪张加速卡被哪个容器占用"
# 对应技能 gpu-container-lookup（../SKILL.md）：卡 -> 占用进程 PID -> 反查容器名。
#
# 用法:
#   gpu-container-lookup.sh <节点IP或ssh别名> [卡Index ...]
#
# - 节点给 ssh 别名最好（自动携带 Port/ProxyJump/IdentityFile）；给裸 IP 时会到
#   ~/.ssh/config 里找匹配的 Host 别名（如 192.167.252.35 -> sdaa-192.167.252.35）。
# - 卡号可选、可给多个；不给则扫描全部卡。卡 Index 从 0 开始。
# - 支持太初卡（teco-smi）与 NVIDIA（nvidia-smi）两类节点。
# - 容器反查：docker top 为主，/proc/<PID>/cgroup 兜底；查不到即宿主机进程。
# - RemoteForward 15721 触发的 "remote port forwarding failed" 警告已用 LogLevel=ERROR 屏蔽。
# - docker 权限不足时自动降级 sudo -n，否则会把容器内进程误报成宿主机进程。

set -u

usage() {
  cat >&2 <<'EOF'
用法: gpu-container-lookup.sh <节点IP或ssh别名> [卡Index ...]
示例:
  gpu-container-lookup.sh sdaa-192.167.252.35 2 3   # tc35 的卡 2、3
  gpu-container-lookup.sh 192.167.252.34           # tc34 全部卡（裸IP自动匹配别名）
  gpu-container-lookup.sh 172.16.240.15 0          # H100 节点（经跳板机）
EOF
  exit 2
}

die() { echo "错误: $*" >&2; exit 1; }

[ $# -ge 1 ] || usage
NODE_INPUT=$1
shift
CARDS=("$@")

SSH="ssh -o BatchMode=yes -o ConnectTimeout=15 -o LogLevel=ERROR"

# ---- 1. 解析节点：裸 IP -> ~/.ssh/config 的 Host 别名 --------------------
resolve_node() {
  local input=$1 cfg=$HOME/.ssh/config token
  [ -f "$cfg" ] || { echo "$input"; return; }
  token=$(awk -v N="$input" '
    /^[[:space:]]*Host[[:space:]]/ && !/\*/ {
      for (i = 2; i <= NF; i++)
        if ($i == N || $i ~ ("-" N "$")) { print $i; exit }
    }' "$cfg" | head -1)
  echo "${token:-$input}"
}
NODE=$(resolve_node "$NODE_INPUT")
$SSH "$NODE" true 2>/dev/null || die "无法 SSH 连接 $NODE（检查别名/网络/密钥）"

# ---- 2. 探测卡类型 -------------------------------------------------------
probe=$($SSH "$NODE" '
  [ -x /opt/tecoai/bin/teco-smi ] && echo HAS_TECO
  command -v nvidia-smi >/dev/null 2>&1 && echo HAS_NVIDIA
  exit 0' 2>/dev/null)
CARD_TYPE=auto
case "$probe" in
  *HAS_TECO*)   CARD_TYPE=teco ;;
  *HAS_NVIDIA*) CARD_TYPE=nvidia ;;
  *) die "$NODE 上未找到 /opt/tecoai/bin/teco-smi 或 nvidia-smi，无法识别卡类型" ;;
esac

# ---- 3. 采集卡与进程，统一成 C/P 记录 ------------------------------------
# C: C <Index> <Bus-Id> <卡已用显存> <卡总显存> <利用率>
# P: P <Index> <PID> <进程名> <进程显存>
RAW=""
collect_teco() {
  local out
  out=$($SSH "$NODE" '/opt/tecoai/bin/teco-smi 2>&1')
  case "$out" in
    *"Permission denied"*) out=$($SSH "$NODE" 'sudo -n /opt/tecoai/bin/teco-smi 2>&1') ;;
  esac
  case "$out" in
    *"Permission denied"*|*"not found"*)
      die "teco-smi 执行失败: $(printf '%s\n' "$out" | tail -1)" ;;
  esac
  RAW=$out
  printf '%s\n' "$out" | awk '
    /^[|][ ]*[0-9]+[ ]+[A-Za-z]/ { idx=$2; bus=$5; util=$8; pend=1; next }
    pend && /MB/ { printf "C\t%s\t%s\t%s\t%s\t%s\n", idx, bus, $5, $7, util; pend=0; next }
    /Processes:/ { inproc=1; next }
    inproc && /^[|][ ]*[0-9]+[ ]+[0-9]+/ {
      name = ""
      for (i = 4; i <= NF-3; i++) name = name (name == "" ? "" : " ") $i
      printf "P\t%s\t%s\t%s\t%s\n", $2, $3, (name == "" ? "-" : name), $(NF-2)
    }'
}

collect_nvidia() {
  $SSH "$NODE" '
    nvidia-smi --query-gpu=index,gpu_uuid,pci.bus_id,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits 2>/dev/null
    echo ===NAMES===
    nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader 2>/dev/null
    echo ===APPS===
    nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader,nounits 2>/dev/null
    exit 0' 2>/dev/null | awk -F', *' '
    /^===NAMES===/ { sec = "n"; next }
    /^===APPS===/  { sec = "a"; next }
    sec == "" {
      if (NF >= 6 && $1 ~ /^[0-9]+$/) {
        printf "C\t%s\t%s\t%sMB\t%sMB\t%s%%\n", $1, $3, $4, $5, $6
        u2i[$2] = $1
      }
      next
    }
    sec == "n" {
      if ($1 ~ /^[0-9]+$/) np[$1] = ($2 == "" || $2 == "[Not Supported]") ? "-" : $2
      next
    }
    sec == "a" {
      if ($2 ~ /^[0-9]+$/ && u2i[$1] != "")
        printf "P\t%s\t%s\t%s\t%s\n", u2i[$1], $2, (($2 in np && np[$2] != "") ? np[$2] : "-"), $3
    }'
}

if [ "$CARD_TYPE" = teco ]; then PARSED=$(collect_teco); else PARSED=$(collect_nvidia); fi
[ -n "$PARSED" ] || die "未能从 $NODE 采集到卡信息（$CARD_TYPE）"

declare -A BUS MEMU MEMT UTIL PIDS_OF PNAME PMEM CTR
CARD_IDX=()
while IFS=$'\t' read -r tag a b c d e; do
  case "$tag" in
    C) CARD_IDX+=("$a"); BUS["$a"]=$b; MEMU["$a"]=$c; MEMT["$a"]=$d; UTIL["$a"]=$e ;;
    P) PIDS_OF["$a"]+="$b "; PNAME["$b"]=$c; PMEM["$a:$b"]=$d ;;
  esac
done <<< "$PARSED"
if [ ${#CARD_IDX[@]} -eq 0 ]; then
  printf '%s\n' "--- 原始 $CARD_TYPE 输出（解析失败，供核对格式） ---" "${RAW:-（未采集到）}" >&2
  die "未能从 $CARD_TYPE 输出中解析出卡列表"
fi

# ---- 4. 校验请求的卡号 ---------------------------------------------------
TARGET=()
if [ ${#CARDS[@]} -gt 0 ]; then
  for c in "${CARDS[@]}"; do
    [[ "$c" =~ ^[0-9]+$ ]] || die "卡号必须是数字: $c"
    [ -n "${BUS[$c]:-}" ] || die "$NODE 没有 Index $c 的卡（现有 Index: ${CARD_IDX[*]}）"
    TARGET+=("$c")
  done
else
  TARGET=("${CARD_IDX[@]}")
fi

# ---- 5. PID 反查容器名（一次 SSH 完成） ----------------------------------
ALL_PIDS=$(awk -F'\t' '$1 == "P" {print $3}' <<< "$PARSED" | sort -u)
lookup_out=""
if [ -n "$ALL_PIDS" ]; then
  # shellcheck disable=SC2086
  lookup_out=$($SSH "$NODE" bash -s -- $ALL_PIDS 2>/dev/null <<'REMOTE'
DOCKER="docker"
$DOCKER ps -q >/dev/null 2>&1 || DOCKER="sudo -n docker"
declare -A owner=()
tmp=$(mktemp) || exit 0
for c in $($DOCKER ps -q 2>/dev/null); do
  n=$($DOCKER inspect -f '{{.Name}}' "$c" 2>/dev/null | sed 's#^/##')
  [ -z "$n" ] && continue
  $DOCKER top "$c" 2>/dev/null | awk -v N="$n" '$2 ~ /^[0-9]+$/ {print $2 "\t" N}'
done > "$tmp"
while IFS=$'\t' read -r p n; do owner["$p"]=$n; done < "$tmp"
rm -f "$tmp"
for P in "$@"; do
  if [ -n "${owner[$P]:-}" ]; then
    echo "MAP $P ${owner[$P]}"
  elif [ ! -d "/proc/$P" ]; then
    echo "GONE $P"
  else
    cid=$(grep -oE 'docker[-/][0-9a-fA-F]{12,}|cri-containerd-[0-9a-fA-F]{12,}|containerd[-/][0-9a-fA-F]{12,}' "/proc/$P/cgroup" 2>/dev/null | head -1 | grep -oE '[0-9a-fA-F]{12,}$')
    if [ -n "$cid" ]; then
      n=$($DOCKER ps --no-trunc --format '{{.ID}} {{.Names}}' 2>/dev/null | awk -v C="$cid" 'index($1, C) == 1 {print $2; exit}')
      echo "MAP $P ${n:-容器ID:$cid}"
    else
      echo "HOST $P"
    fi
  fi
done
REMOTE
  )
  if [ -z "$lookup_out" ]; then
    echo "警告: 容器反查无结果（docker 不可用或进程刚好退出），容器列将显示 ?" >&2
  fi
fi

while read -r tag pid rest; do
  case "$tag" in
    MAP)  CTR["$pid"]=$rest ;;
    GONE) CTR["$pid"]="（进程已退出）" ;;
    HOST) CTR["$pid"]="宿主机进程" ;;
  esac
done <<< "${lookup_out:-}"

# ---- 6. 输出 -------------------------------------------------------------
busy=() idle=() stuck=()
for idx in "${TARGET[@]}"; do
  if [ -n "${PIDS_OF[$idx]:-}" ]; then
    busy+=("$idx")
  else
    used=${MEMU[$idx]%MB}
    if [ "${used:-0}" -gt 0 ] 2>/dev/null; then stuck+=("$idx"); else idle+=("$idx"); fi
  fi
done

scope="全部卡"
[ ${#CARDS[@]} -gt 0 ] && scope="卡 ${CARDS[*]}"
echo "节点: $NODE_INPUT（$NODE）  卡型: $CARD_TYPE  共 ${#CARD_IDX[@]} 张  查询: $scope"
echo

if [ ${#busy[@]} -eq 0 ]; then
  echo "查询范围内没有进程占用加速卡。"
fi
for idx in "${busy[@]}"; do
  cs=$(for pid in ${PIDS_OF[$idx]}; do echo "${CTR[$pid]:-?}"; done | sort -u | paste -sd'、' -)
  echo "卡 $idx -> $cs"
done
[ ${#busy[@]} -gt 0 ] && echo

if [ ${#busy[@]} -gt 0 ]; then
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "Index" "Bus-Id" "卡显存" "Util" "PID" "进程" "进程显存" "容器名"
  for idx in "${busy[@]}"; do
    for pid in ${PIDS_OF[$idx]}; do
      printf '%s\t%s\t%s/%s\t%s\t%s\t%s\t%sMB\t%s\n' \
        "$idx" "${BUS[$idx]}" "${MEMU[$idx]}" "${MEMT[$idx]}" "${UTIL[$idx]}" \
        "$pid" "${PNAME[$pid]}" "${PMEM[$idx:$pid]:-?}" "${CTR[$pid]:-?}"
    done
  done
  echo
fi

[ ${#idle[@]} -gt 0 ] && echo "无进程且显存为空: Index ${idle[*]}"
[ ${#stuck[@]} -gt 0 ] && echo "无进程但显存未释放: Index ${stuck[*]}"
echo "注: 卡 Index 从 0 开始（Index 2 = 第 3 张物理卡）；容器列 \"?\" 表示反查失败。"
