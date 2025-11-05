#!/bin/bash
# Diagnostic script for tunnel issues

echo "=== Tunnel Diagnostic Script ==="
echo ""

echo "1. Checking gost process command line:"
echo "   PID 7047 command:"
docker exec smite-panel cat /proc/7047/cmdline 2>/dev/null | tr '\0' ' ' || echo "   Could not read process (may have died)"
echo ""

echo "2. Testing connectivity from panel to node (65.109.197.226:10000):"
docker exec smite-panel timeout 3 bash -c 'cat < /dev/null > /dev/tcp/65.109.197.226/10000' 2>&1 && echo "   ✅ Connection OK" || echo "   ❌ Connection FAILED"
echo ""

echo "3. Checking panel logs for gost:"
docker logs smite-panel 2>&1 | grep -i gost | tail -10
echo ""

echo "4. Testing local connection to gost (127.0.0.1:8080):"
timeout 3 bash -c 'cat < /dev/null > /dev/tcp/127.0.0.1/8080' 2>&1 && echo "   ✅ Port 8080 is accessible" || echo "   ❌ Port 8080 not accessible"
echo ""

echo "5. Checking if Xray on node is listening on 0.0.0.0 or 127.0.0.1:"
echo "   (Xray should listen on 0.0.0.0 to accept connections from panel)"
echo ""

echo "=== Diagnosis complete ==="

