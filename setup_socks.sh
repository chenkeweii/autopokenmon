#!/bin/bash
# setup_socks_v3.sh

set -uo pipefail # 移除了 -e，改为手动处理关键错误，防止 grep 导致退出

# ── 自动检测网卡 ──────────────────────────────────────────
# 优先找 enp1s0，找不到就找默认路由出口网卡
IFACE="enp1s0"
if ! ip link show "$IFACE" >/dev/null 2>&1; then
    IFACE=$(ip route | grep default | awk '{print $5}' | head -n1)
fi

BASE_PORT=10000
PIDDIR="/var/run/socks"
LOGDIR="/var/log/socks"
MICROSOCKS_BIN="/usr/local/bin/microsocks"
BASE_TABLE=100
LAN_RANGES=("10.0.0.0/8" "172.16.0.0/12" "192.168.0.0/16" "127.0.0.0/8")

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

[[ $EUID -ne 0 ]] && error "请用 root 运行"

# ── 1. 环境准备与内核优化 ──────────────────────────────────
install_deps() {
    info "优化内核参数与检查依赖..."
    sysctl -w net.ipv4.conf.all.rp_filter=2 >/dev/null 2>&1
    sysctl -w net.ipv4.conf.default.rp_filter=2 >/dev/null 2>&1
    
    if ! command -v microsocks &>/dev/null; then
        info "正在安装 microsocks..."
        apt-get update -qq && apt-get install -y -qq git gcc make >/dev/null
        local tmpdir=$(mktemp -d)
        git clone --depth=1 https://github.com/rofl0r/microsocks.git "$tmpdir" >/dev/null 2>&1
        make -C "$tmpdir" -s && install -m 755 "$tmpdir/microsocks" "$MICROSOCKS_BIN"
        rm -rf "$tmpdir"
    fi
}

# ── 2. 彻底清理旧规则（修复报错退出的关键） ──────────────────
cleanup() {
    info "清理旧进程和路由规则..."
    pkill -f microsocks 2>/dev/null || true
    
    # 使用 || true 确保 grep 找不到东西时脚本不崩溃
    local rules
    rules=$(iptables -t mangle -S OUTPUT 2>/dev/null | grep "SOCKS_PROXY" || true)
    if [[ -n "$rules" ]]; then
        echo "$rules" | sed 's/-A/-D/' | while read -r line; do
            iptables -t mangle $line 2>/dev/null || true
        done
    fi

    # 清理策略路由表
    local max_ips=200 
    for tbl in $(seq "$BASE_TABLE" $((BASE_TABLE + max_ips))); do
        [[ "$tbl" -ge 253 && "$tbl" -le 255 ]] && continue
        ip rule del table "$tbl" 2>/dev/null || true
        ip route flush table "$tbl" 2>/dev/null || true
    done
}

# ── 3. 防火墙自动放行 ──────────────────────────────────────
setup_firewall() {
    local port_start=$1
    local count=$2
    local port_end=$((port_start + count - 1))
    info "开放防火墙端口: $port_start - $port_end"
    
    if command -v ufw &>/dev/null && ufw status | grep -q "active"; then
        ufw allow "$port_start:$port_end/tcp" >/dev/null
    elif command -v firewall-cmd &>/dev/null && firewall-cmd --state &>/dev/null; then
        firewall-cmd --add-port="$port_start-$port_end/tcp" --permanent >/dev/null
        firewall-cmd --reload >/dev/null
    fi
}

# ── 4. 路由与启动逻辑 ──────────────────────────────────────
setup_routing() {
    local ip=$1 port=$2 table=$3 gw=$4
    local mark=$table
    local user="socks${port}"

    # 路由表
    ip route add default via "$gw" src "$ip" dev "$IFACE" table "$table" 2>/dev/null || true
    ip rule add fwmark "$mark" table "$table" priority $((10000 + mark)) 2>/dev/null || true

    id "$user" &>/dev/null || useradd -r -s /usr/sbin/nologin "$user"
    local uid=$(id -u "$user")

    # 关键：先接受内网流量（回程路由白名单）
    for range in "${LAN_RANGES[@]}"; do
        iptables -t mangle -A OUTPUT -m owner --uid-owner "$uid" -d "$range" -m comment --comment "SOCKS_PROXY" -j ACCEPT
    done
    # 公网流量打标记
    iptables -t mangle -A OUTPUT -m owner --uid-owner "$uid" -m comment --comment "SOCKS_PROXY" -j MARK --set-mark "$mark"
}

start_proxy() {
    local ip=$1 port=$2
    local user="socks${port}"
    mkdir -p "$LOGDIR" "$PIDDIR"
    local logfile="${LOGDIR}/socks_${port}.log"
    touch "$logfile" && chown "$user" "$logfile"

    su -s /bin/sh "$user" -c "$MICROSOCKS_BIN -i 0.0.0.0 -p ${port} >> ${logfile} 2>&1" &
    echo $! > "$PIDDIR/socks_${port}.pid"
}

# ════════════════════════════════════════════════════════
#  执行流程
# ════════════════════════════════════════════════════════

install_deps
cleanup

GW=$(ip route show dev "$IFACE" | awk '/default/ {print $3; exit}')
[[ -z "$GW" ]] && error "无法检测到网关，请手动检查网卡 $IFACE"

mapfile -t IPS < <(ip -4 addr show dev "$IFACE" | awk '/inet / {split($2,a,"/"); print a[1]}')
[[ ${#IPS[@]} -eq 0 ]] && error "网卡 $IFACE 上没有 IP"

setup_firewall "$BASE_PORT" "${#IPS[@]}"

info "检测到网卡: $IFACE, 网关: $GW, IP 数量: ${#IPS[@]}"
LAN_IP=$(ip -4 addr | grep -v '127.0.0.1' | awk '/inet / {print $2}' | cut -d/ -f1 | head -n1)

PORT=$BASE_PORT
TABLE=$BASE_TABLE
for IP in "${IPS[@]}"; do
    setup_routing "$IP" "$PORT" "$TABLE" "$GW"
    start_proxy "$IP" "$PORT"
    printf "  [启动中] 端口: %-5d -> 出站 IP: %-15s\n" "$PORT" "$IP"
    ((PORT++)); ((TABLE++))
done

echo -e "\n${GREEN}全部任务已提交！${NC}"
echo "测试方法：socks5://${LAN_IP}:${BASE_PORT}"
echo "如果仍无法连接，请尝试执行：sysctl -w net.ipv4.conf.${IFACE}.rp_filter=0"