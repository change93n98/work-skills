#!/usr/bin/env bash
set -u -o pipefail

log_file=${1:?需要阶段日志路径}
shift
: "${1:?需要执行的命令}"

mkdir -p -- "$(dirname -- "$log_file")" || exit $?
: >> "$log_file" || exit $?

{
  printf '[%s] 开始\n' "$(date -Ins)"
  status=0
  "$@" || status=$?
  printf '[%s] 结束 exit=%s\n' "$(date -Ins)" "$status"
  exit "$status"
} 2>&1 | tee -a -- "$log_file"
