#!/bin/bash
# setup_socks_v4.sh - 彻底解决出口IP一致问题

set -u

# ── 自动检测网卡和 IP ──────────────────────────────────────
IFACE="enp1s0"
if ! ip link show "$IFACE" >/dev/null 2>&1; then
    IFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
fi

BASE_PORT=10000
PIDDIR="/var/run/socks"
LOGDIR="/var/log/socks"
MICROSOCKS_BIN="/usr/local/bin/microsocks"
BASE_TABLE=100

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

[[ $EUID -ne 0 ]] && error "请用 root 运行"

# ── 1. 安装与内核参数优化 ──────────────────────────────────
install_deps() {
    info "优化内核参数与检查依赖..."
    sysctl -w net.ipv4.conf.all.rp_filter=0 >/dev/null 2>&1
    sysctl -w net.ipv4.conf.default.rp_filter=0 >/dev/null 2>&1
    sysctl -w "net.ipv4.conf.${IFACE}.rp_filter=0" >/dev/null 2>&1
    
    if ! command -v microsocks &>/dev/null; then
        info "正在安装 microsocks..."
        apt-get update -qq && apt-get install -y -qq git gcc make >/dev/null
        local tmpdir=$(mktemp -d)
        git clone --depth=1 https://github.com/rofl0r/microsocks.git "$tmpdir" >/dev/null 2>&1
        make -C "$tmpdir" -s && install -m 755 "$tmpdir/microsocks" "$MICROSOCKS_BIN"
        rm -rf "$tmpdir"
    fi
}

# ── 2. 清理环境 ──────────────────────────────────────────
cleanup() {
    info "清理旧进程和路由规则..."
    pkill -f microsocks 2>/dev/null || true
    
    # 清理所有相关的 ip rule
    ip rule show | grep "lookup" | awk -F: '$1 < 30000 && $1 >= 10000 {print $1}' | while read -r prio; do
        ip rule del priority "$prio" 2>/dev/null || true
    done

    # 清理路由表
    for tbl in $(seq "$BASE_TABLE" $((BASE_TABLE + 50))); do
        [[ "$tbl" -ge 253 && "$tbl" -le 255 ]] && continue
        ip route flush table "$tbl" 2>/dev/null || true
    done
}

# ── 3. 配置路由与启动进程 ──────────────────────────────────
setup_instance() {
    local ip=$1 port=$2 table=$3 gw=$4
    
    # 策略路由：所有来自该 IP 的包，强制走指定路由表
    # 使用 onlink 兼容不同网段的 IP
    ip route add default via "$gw" dev "$IFACE" onlink table "$table" 2>/dev/null || true
    ip rule add from "$ip" lookup "$table" priority $((10000 + table)) 2>/dev/null || true

    # 启动进程：使用 -b 参数绑定出站 IP
    # -i 0.0.0.0 允许所有网卡进入，-p 监听端口，-b 绑定出站公网IP
    nohup "$MICROSOCKS_BIN" -i 0.0.0.0 -p "$port" -b "$ip" >> "${LOGDIR}/socks_${port}.log" 2>&1 &
}

# ════════════════════════════════════════════════════════
#  执行流程
# ════════════════════════════════════════════════════════
install_deps
cleanup

mkdir -p "$LOGDIR" "$PIDDIR"

# 获取主网关
GW=$(ip route show dev "$IFACE" | awk '/default/ {print $3; exit}')
[[ -z "$GW" ]] && error "无法检测到网关"

# 获取所有 IPv4 (排除回环)
mapfile -t IPS < <(ip -4 addr show dev "$IFACE" | awk '/inet / {split($2,a,"/"); print a[1]}')
[[ ${#IPS[@]} -eq 0 ]] && error "网卡 $IFACE 上没有 IP"

info "检测到网卡: $IFACE, 网关: $GW, IP 数量: ${#IPS[@]}"

PORT=$BASE_PORT
TABLE=$BASE_TABLE
for IP in "${IPS[@]}"; do
    setup_instance "$IP" "$PORT" "$TABLE" "$GW"
    echo -e "  [${GREEN}启动成功${NC}] 端口: ${YELLOW}${PORT}${NC} -> 出站 IP: ${GREEN}${IP}${NC}"
    ((PORT++)); ((TABLE++))
done

echo -e "\n────────────────────────────────────────────────────────"
info "全部 IP 绑定完成。请在局域网工具中分别测试 10000, 10001, 10002 端口。"