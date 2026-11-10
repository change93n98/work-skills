#!/usr/bin/env bash
set -eu

server=${1:?需要诊断服务地址 host:port}
warmup_script=${2:?需要本次预热脚本}
request_script=${3:?需要本次正式请求脚本}
shift 3

if [[ ! -r "$warmup_script" ]]; then
  printf '无法读取预热脚本 %s\n' "$warmup_script" >&2
  exit 2
fi
if [[ ! -r "$request_script" ]]; then
  printf '无法读取请求脚本 %s\n' "$request_script" >&2
  exit 2
fi

stop_profile() {
  local request_status=$?
  local stop_status=0
  trap - EXIT
  printf '停止采集\n'
  curl --noproxy '*' -fsS --connect-timeout 5 -X POST "http://$server/stop_profile" || stop_status=$?
  if (( request_status != 0 )); then
    exit "$request_status"
  fi
  exit "$stop_status"
}

printf '开始预热\n'
bash -- "$warmup_script"

printf '开始采集\n'
curl --noproxy '*' -fsS --connect-timeout 5 -X POST "http://$server/start_profile"
trap stop_profile EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
bash -- "$request_script" "$@"
