#!/usr/bin/env bash
CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
echo ""
echo -e "${CYAN}${BOLD} ===============================================${NC}"
echo -e "${CYAN}${BOLD}   G.R.I.D AI — Compliance Management System${NC}"
echo -e "${CYAN}${BOLD}   by Ali Moyo${NC}"
echo -e "${CYAN}${BOLD} ===============================================${NC}"
echo ""
if ! command -v node &>/dev/null; then
    echo -e "${RED}[ERROR] Node.js not installed. Install from https://nodejs.org${NC}"; exit 1
fi
echo -e "  Node.js: ${GREEN}$(node --version)${NC}"
if [ ! -d "node_modules" ]; then
    echo -e "\n${YELLOW}[SETUP] Installing dependencies...${NC}"
    npm install && echo -e "${GREEN}[OK] Done.${NC}"
fi
PORT=3000
if [ -f ".env" ]; then
    FOUND=$(grep "^PORT=" .env 2>/dev/null | head -1)
    [ -n "$FOUND" ] && PORT="${FOUND#PORT=}"
fi
echo ""
echo -e "  ${CYAN}-----------------------------------------------${NC}"
echo -e "  ${BOLD}URL:      ${GREEN}http://localhost:${PORT}${NC}"
echo -e "  ${BOLD}Login:    ${NC}admin@auditsphere.local"
echo -e "  ${BOLD}Password: ${NC}admin123"
echo -e "  ${CYAN}-----------------------------------------------${NC}"
echo -e "  Features: AI · Vendors · OneDrive · Teams"
echo -e "            Approvals · NCs · Activity Log"
echo -e "  ${CYAN}-----------------------------------------------${NC}"
echo ""
echo -e "  Press ${BOLD}Ctrl+C${NC} to stop."
echo ""
open_browser() {
    sleep 2
    if command -v xdg-open &>/dev/null; then xdg-open "http://localhost:${PORT}" 2>/dev/null
    elif command -v open &>/dev/null; then open "http://localhost:${PORT}" 2>/dev/null; fi
}
open_browser &
node src/server.js
