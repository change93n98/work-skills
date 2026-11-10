#!/usr/bin/env bash
set -eu

dump_run_dir=${1:?需要服务端 dump 目录的绝对路径}
request_script=${2:?需要正式客户端脚本}
shift 2
test -r "$request_script"

# 在服务启动和所有预热完成后执行一次。
mkdir -- "$dump_run_dir/before_formal"
for dump_dir in dump_info lmk_dump; do
  if [[ -d "$dump_run_dir/$dump_dir" ]]; then
    mv -- "$dump_run_dir/$dump_dir" "$dump_run_dir/before_formal/"
  fi
  mkdir -- "$dump_run_dir/$dump_dir"
done

date -Ins > "$dump_run_dir/request_start.txt"
request_status=0
bash -- "$request_script" "$@" || request_status=$?
date -Ins > "$dump_run_dir/request_end.txt"
exit "$request_status"
